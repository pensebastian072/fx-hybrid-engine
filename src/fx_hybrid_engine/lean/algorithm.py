"""Lean/QuantConnect algorithm wrapper for the fx-hybrid-engine pipeline."""
from __future__ import annotations

import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_hybrid_engine.lean.qc_state_store import load_state, save_state
from fx_hybrid_engine.lean.runtime_safety import evaluate_runtime_safety
from fx_hybrid_engine.ops.circuit_breakers import BreakerContext
from fx_hybrid_engine.ops.execution_policy import apply_close_only_policy
from fx_hybrid_engine.ops.health import HealthPolicy
from fx_hybrid_engine.ops.ladder import resolve_ladder_caps

logger = logging.getLogger("fxhe.lean.algorithm")

# Lean runtime symbols — only available inside the Lean engine
try:
    from AlgorithmImports import *  # noqa: F401, F403

    _LEAN_AVAILABLE = True
except ImportError:
    _LEAN_AVAILABLE = False

    class QCAlgorithm:  # type: ignore[no-redef]
        """Test/import stub when LEAN runtime is unavailable."""

        def Debug(self, msg: str) -> None: ...  # noqa: N802
        def Log(self, msg: str) -> None: ...  # noqa: N802
        def SetStartDate(self, *a, **kw) -> None: ...  # noqa: N802
        def SetEndDate(self, *a, **kw) -> None: ...  # noqa: N802
        def SetCash(self, amount: float) -> None: ...  # noqa: N802
        def AddForex(self, *a, **kw): ...  # noqa: N802
        def SetHoldings(self, sym, pct: float) -> None: ...  # noqa: N802
        def Liquidate(self, sym=None) -> None: ...  # noqa: N802
        def SetWarmUp(self, *a, **kw) -> None: ...  # noqa: N802
        def History(self, *a, **kw): ...  # noqa: N802
        def GetParameter(self, key: str) -> str: ...  # noqa: N802

        Resolution = type("Resolution", (), {"Minute": "Minute", "Hour": "Hour", "Daily": "Daily"})()

    Resolution = QCAlgorithm.Resolution


def _map_resolution(freq: str):
    key = str(freq).lower()
    if key == "1d":
        return Resolution.Daily
    if key == "1h":
        return Resolution.Hour
    # 15m defaults to minute bars in QC and relies on internal aggregation in strategy loop.
    return Resolution.Minute


def _to_utc(ts: object) -> pd.Timestamp:
    out = pd.Timestamp(ts)
    if out.tzinfo is None:
        return out.tz_localize("UTC")
    return out.tz_convert("UTC")


class FxHybridAlgorithm(QCAlgorithm):
    """Lean algorithm that runs the hybrid pipeline with QC paper safety controls."""

    def Initialize(self) -> None:  # noqa: N802
        from fx_hybrid_engine.data.feature_store import FeatureStore
        from fx_hybrid_engine.engines.pairs import PairsEngine
        from fx_hybrid_engine.engines.trend import TrendEngine
        from fx_hybrid_engine.portfolio.builder import PortfolioBuilder
        from fx_hybrid_engine.regime.orchestrator import RegimeOrchestrator
        from fx_hybrid_engine.risk.controls import RiskController
        from fx_hybrid_engine.utils.config import load_config

        config_path = Path(self.GetParameter("config_path") or "config/default.yaml")
        self._cfg = load_config(config_path)
        self._resolution = _map_resolution(self._cfg.qc_runtime.resolution)

        # Minimal deterministic defaults for QC paper startup.
        self.SetStartDate(2022, 1, 1)
        self.SetCash(100000)

        self._symbols: dict[str, object] = {}
        all_syms = sorted(list({s for pair in self._cfg.pair_list for s in pair} | set(self._cfg.trend_symbols)))
        for sym in all_syms:
            forex = self.AddForex(sym, self._resolution, market="oanda")
            self._symbols[sym] = forex.Symbol

        self._feature_store = FeatureStore()
        self._pairs_engine = PairsEngine(self._cfg.pairs)
        self._trend_engine = TrendEngine(self._cfg.trend)
        self._orchestrator = RegimeOrchestrator(self._cfg.regime, self._cfg.risk)
        self._portfolio_builder = PortfolioBuilder(self._cfg.risk)
        self._risk_ctrl = RiskController(self._cfg.risk, initial_equity=1.0)

        self._health_state = "DATA_OK"
        self._close_only = False
        self._consecutive_rejects = 0
        self._expected_positions: dict[str, float] = {}
        self._last_bar_time: pd.Timestamp | None = None
        self._last_reconcile_at: pd.Timestamp | None = None
        self._mismatch_cycles = 0
        self._consecutive_losses = 0
        self._daily_start_equity = 1.0
        self._weekly_start_equity = 1.0
        self._last_date = None
        self._last_week = None
        self._run_id = self.GetParameter("run_id") or datetime.now(UTC).strftime("qc_%Y%m%d_%H%M%S")
        self._ladder_stage = str(self._cfg.micro_live_ladder.active_stage)
        self._state_namespace = f"{self._cfg.qc_runtime.state_store_namespace}/{self._run_id}"

        persisted = load_state(namespace=self._state_namespace, owner=self)
        if persisted:
            self._close_only = bool(persisted.get("close_only", False))
            self._health_state = str(persisted.get("health_state", "DATA_OK"))
            self._ladder_stage = str(persisted.get("ladder_stage", self._ladder_stage))
            self._expected_positions = {
                str(k): float(v) for k, v in (persisted.get("expected_positions") or {}).items()
            }

        # Load pre-trained models with versioned path preference.
        try:
            self._trend_engine.load_model_version()
        except Exception:  # noqa: BLE001
            self._trend_engine.load_model()
        self._orchestrator.load_model()

        warm_up_bars = max(self._cfg.trend.sma_slow, self._cfg.pairs.spread_window, self._cfg.regime.obs_window)
        self.SetWarmUp(timedelta(days=int(warm_up_bars)))
        self.Log(
            f"FxHybridAlgorithm initialized; symbols={all_syms}, resolution={self._cfg.qc_runtime.resolution}, stage={self._ladder_stage}"
        )

    def _portfolio_weights(self) -> dict[str, float]:
        if not _LEAN_AVAILABLE:
            return {}
        out: dict[str, float] = {}
        total_value = float(getattr(self.Portfolio, "TotalPortfolioValue", 0.0) or 0.0)
        if total_value <= 0:
            return out
        for sym_str, lean_sym in self._symbols.items():
            h = self.Portfolio[lean_sym]
            if not h.Invested and abs(float(h.Quantity)) < 1e-12:
                continue
            value = float(h.HoldingsValue)
            out[sym_str] = value / total_value
        return out

    def _compute_returns_context(self) -> BreakerContext:
        if not _LEAN_AVAILABLE:
            return BreakerContext(0.0, 0.0, self._consecutive_losses, 1.0, self._consecutive_rejects)
        now = _to_utc(self.Time)
        total_value = float(getattr(self.Portfolio, "TotalPortfolioValue", 1.0) or 1.0)
        day_key = now.date()
        week_key = now.isocalendar()[:2]
        if self._last_date != day_key:
            self._daily_start_equity = total_value
            self._last_date = day_key
        if self._last_week != week_key:
            self._weekly_start_equity = total_value
            self._last_week = week_key
        daily_return = (total_value / max(1e-9, self._daily_start_equity)) - 1.0
        weekly_return = (total_value / max(1e-9, self._weekly_start_equity)) - 1.0
        return BreakerContext(
            daily_return=float(daily_return),
            weekly_return=float(weekly_return),
            consecutive_losses=int(self._consecutive_losses),
            realized_vol_multiple=1.0,
            reject_count=int(self._consecutive_rejects),
        )

    def _apply_ladder_caps(self, targets: dict[str, float]) -> dict[str, float]:
        caps = resolve_ladder_caps(stage=self._ladder_stage)
        clipped = {
            sym: max(-caps.per_symbol_risk_cap, min(caps.per_symbol_risk_cap, float(w)))
            for sym, w in targets.items()
        }
        gross = sum(abs(v) for v in clipped.values())
        if gross <= caps.max_gross_exposure or gross <= 1e-12:
            return clipped
        scale = caps.max_gross_exposure / gross
        return {k: v * scale for k, v in clipped.items()}

    def _save_runtime_state(self) -> None:
        payload = {
            "close_only": self._close_only,
            "health_state": self._health_state,
            "ladder_stage": self._ladder_stage,
            "expected_positions": self._expected_positions,
            "last_bar_time": self._last_bar_time.isoformat() if self._last_bar_time is not None else None,
        }
        save_state(namespace=self._state_namespace, payload=payload, owner=self)

    def OnData(self, data) -> None:  # noqa: N802
        if self.IsWarmingUp:
            return

        now = _to_utc(self.Time)
        self._last_bar_time = now
        health_policy = HealthPolicy(
            data_stale_seconds=int(self._cfg.health_monitor.state_machine_thresholds.get("data_stale_seconds", 300)),
            degraded_rejects=int(self._cfg.health_monitor.state_machine_thresholds.get("degraded_rejects", 3)),
            broker_down_rejects=int(self._cfg.health_monitor.state_machine_thresholds.get("broker_down_rejects", 8)),
            max_missing_bars=1,
        )
        safety = evaluate_runtime_safety(
            run_id=self._run_id,
            last_bar_timestamp_utc=self._last_bar_time,
            consecutive_rejects=self._consecutive_rejects,
            missing_bars=0,
            broker_connected=True,
            health_policy=health_policy,
            breaker_ctx=self._compute_returns_context(),
            circuit_breakers_cfg=self._cfg.circuit_breakers,
            reconciliation_cfg=self._cfg.reconciliation,
            expected_holdings=self._expected_positions,
            actual_holdings=self._portfolio_weights(),
            expected_order_ids=set(),
            actual_order_ids=set(),
            mismatch_cycles=self._mismatch_cycles,
        )
        self._health_state = safety.health_state
        self._close_only = bool(safety.close_only)
        if safety.reconciliation is not None and safety.reconciliation.pause_entries:
            self._mismatch_cycles += 1
        else:
            self._mismatch_cycles = 0

        # Build symbol->DataFrame from recent history.
        warm = max(self._cfg.trend.sma_slow, self._cfg.pairs.spread_window) + 10
        bar_data: dict[str, pd.DataFrame] = {}
        for sym_str, lean_sym in self._symbols.items():
            hist = self.History(lean_sym, warm, self._resolution)
            if hist.empty:
                continue
            df = hist[["open", "high", "low", "close", "volume"]].copy()
            df.index = pd.to_datetime(df.index.get_level_values("time"), utc=True)
            bar_data[sym_str] = df
        if not bar_data:
            self._save_runtime_state()
            return

        # Pipeline
        self._orchestrator.update_regime(bar_data)
        pairs_out = self._pairs_engine.generate(bar_data, now)
        trend_out = self._trend_engine.generate(bar_data, now)
        gated = self._orchestrator.gate(pairs_out, trend_out, now)
        targets = self._portfolio_builder.build(gated)
        current_weights = self._portfolio_weights()
        policy = apply_close_only_policy(current_weights, targets, close_only=self._close_only)
        capped = self._apply_ladder_caps(policy.sanitized_targets)

        if self._close_only and bool(self._cfg.qc_runtime.cancel_on_close_only):
            with suppress(Exception):
                self.Transactions.CancelOpenOrders()

        for sym_str in sorted(set(current_weights.keys()) | set(capped.keys())):
            lean_sym = self._symbols.get(sym_str)
            if lean_sym is None:
                continue
            target = float(capped.get(sym_str, 0.0))
            self.SetHoldings(lean_sym, target)
            self._expected_positions[sym_str] = target

        self.Debug(
            f"state={self._health_state} close_only={self._close_only} "
            f"signals={len([s for s in gated if s.is_active()])} blocked={len(policy.blocked_actions)}"
        )
        self._save_runtime_state()

    def OnOrderEvent(self, orderEvent) -> None:  # noqa: N802
        status = str(getattr(orderEvent, "Status", "")).lower()
        if "invalid" in status or "canceled" in status:
            self._consecutive_rejects += 1
            self._close_only = True
            self.Log(f"Order reject/cancel observed; close_only enabled (consecutive_rejects={self._consecutive_rejects})")
        elif "filled" in status:
            self._consecutive_rejects = max(0, self._consecutive_rejects - 1)
        self._save_runtime_state()

    def OnEndOfAlgorithm(self) -> None:  # noqa: N802
        self._save_runtime_state()
