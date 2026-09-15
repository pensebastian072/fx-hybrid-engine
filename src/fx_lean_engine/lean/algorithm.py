"""LEAN algorithm entrypoint for FX phase."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fx_lean_engine.config import load_backtest_config, load_universe_config
from fx_lean_engine.data.consolidation import BarRouter
from fx_lean_engine.data.universe import SubscriptionRegistry, add_forex_for_alias, normalize_forex_pair
from fx_lean_engine.lean.brokerage import apply_brokerage_model
from fx_lean_engine.orchestration.pipeline import build_runtime_from_configs
from fx_lean_engine.types import Bar

try:
    from AlgorithmImports import QCAlgorithm, Resolution, TradeBarConsolidator  # type: ignore
except Exception:  # pragma: no cover
    class QCAlgorithm:  # type: ignore
        """Fallback for environments without LEAN."""

    class Resolution:  # type: ignore
        """Fallback resolution enum."""

        Minute = "Minute"

    class TradeBarConsolidator:  # type: ignore
        """Fallback consolidator placeholder."""


class FxLeanEngineAlgorithm(QCAlgorithm):
    """Cloud-first LEAN FX algorithm."""

    def Initialize(self) -> None:  # noqa: N802
        project_root = Path(__file__).resolve().parents[3]
        config_dir = Path(os.getenv("FXLE_CONFIG_DIR", str(project_root / "configs")))
        param_backtest_config = ""
        if hasattr(self, "GetParameter"):
            value = self.GetParameter("backtest_config")  # type: ignore[attr-defined]
            param_backtest_config = str(value).strip() if value is not None else ""
        backtest_config_name = param_backtest_config or os.getenv("FXLE_BACKTEST_CONFIG", "backtest_smoke.yaml")

        universe_cfg = load_universe_config(config_dir / "universe.yaml")
        backtest_cfg = load_backtest_config(config_dir / backtest_config_name)
        active_pairs = backtest_cfg.symbols if backtest_cfg.symbols else list(universe_cfg.pairs or [])

        runtime_overrides: dict[str, Any] = {}
        phase2_param = self._read_parameter("phase2_pairs_gating_enabled")
        if phase2_param is not None:
            runtime_overrides["phase2_pairs_gating_enabled"] = self._parse_bool(phase2_param)

        runtime = build_runtime_from_configs(
            config_dir,
            active_symbols=active_pairs,
            runtime_overrides=runtime_overrides or None,
        )

        self._runtime = runtime
        self._registry = SubscriptionRegistry()
        self._canonical_to_symbol: dict[str, Any] = {}
        self._symbol_object_to_canonical: dict[Any, str] = {}
        self._symbol_to_canonical: dict[str, str] = {}
        self._received_consolidated: dict[str, bool] = {}
        self._bar_interval_minutes = int(universe_cfg.consolidated_bar_minutes)
        self._lean_consolidators: dict[str, Any] = {}
        self._router_fallback = BarRouter(interval_minutes=self._bar_interval_minutes)
        self._using_lean_consolidators = False
        self._broker_error_active = False

        start = datetime.fromisoformat(backtest_cfg.start_date)
        end = datetime.fromisoformat(backtest_cfg.end_date)
        if hasattr(self, "SetStartDate"):
            self.SetStartDate(start.year, start.month, start.day)
        if hasattr(self, "SetEndDate"):
            self.SetEndDate(end.year, end.month, end.day)
        if hasattr(self, "SetCash"):
            self.SetCash(float(backtest_cfg.initial_cash))

        apply_brokerage_model(self, runtime.runtime_cfg)

        for pair in active_pairs:
            canonical = normalize_forex_pair(pair)
            symbol = add_forex_for_alias(self, canonical, Resolution.Minute, self._registry)
            self._canonical_to_symbol[canonical] = symbol
            self._symbol_to_canonical[str(symbol)] = canonical
            self._symbol_object_to_canonical[symbol] = canonical
            self._received_consolidated[canonical] = False
            if not self._try_attach_lean_consolidator(canonical, symbol):
                self._router_fallback.register(canonical, self._handle_consolidated_bar)

        if hasattr(self, "SetWarmup"):
            self.SetWarmup(max(60, self._runtime.pairs_cfg.lookback_bars))

        if runtime.runtime_cfg.live_persistence_enabled:
            run_manifest, config_snapshot = self._build_live_metadata(
                project_root=project_root,
                config_dir=config_dir,
                backtest_config_name=backtest_config_name,
                backtest_cfg=backtest_cfg,
            )
            runtime.set_live_metadata(run_manifest, config_snapshot, timestamp=datetime.now(tz=UTC))

        if hasattr(self, "Log"):
            self.Log(f"Subscribed: {', '.join(sorted(self._canonical_to_symbol.keys()))}")
            mode = "LEAN_CONSOLIDATORS" if self._using_lean_consolidators else "FALLBACK_ROUTER"
            self.Log(f"FXLE_CONSOLIDATION_MODE mode={mode} interval={self._bar_interval_minutes}m")

    def OnData(self, data) -> None:  # noqa: N802
        """Fallback minute handler when LEAN consolidators are unavailable."""
        if self._using_lean_consolidators:
            return

        now = datetime.now(tz=UTC)
        bars = getattr(data, "Bars", None)
        if bars is None:
            return

        for canonical, symbol in self._canonical_to_symbol.items():
            if symbol not in bars:
                continue
            tradebar = bars[symbol]
            start = getattr(tradebar, "Time", now - timedelta(minutes=1))
            end = getattr(tradebar, "EndTime", start + timedelta(minutes=1))
            minute_bar = Bar(
                symbol=canonical,
                start=start,
                end=end,
                open=float(tradebar.Open),
                high=float(tradebar.High),
                low=float(tradebar.Low),
                close=float(tradebar.Close),
                volume=float(getattr(tradebar, "Volume", 0.0)),
            )
            self._router_fallback.on_minute_bar(minute_bar)

    def OnOrderEvent(self, order_event) -> None:  # noqa: N802
        """Capture fills/rejects for paper/live persistence and diagnostics."""
        if not hasattr(self, "_runtime"):
            return

        ts = (
            getattr(order_event, "UtcTime", None)
            or getattr(order_event, "Time", None)
            or datetime.now(tz=UTC)
        )
        status = str(getattr(order_event, "Status", ""))
        symbol_obj = getattr(order_event, "Symbol", None)
        canonical = self._symbol_object_to_canonical.get(symbol_obj) or self._symbol_to_canonical.get(str(symbol_obj)) or str(symbol_obj or "")

        self._runtime.record_fill(
            ts,
            symbol=canonical,
            status=status,
            order_id=str(getattr(order_event, "OrderId", "")),
            fill_quantity=float(getattr(order_event, "FillQuantity", 0.0)),
            fill_price=float(getattr(order_event, "FillPrice", 0.0)),
            message=str(getattr(order_event, "Message", "")),
        )

        status_up = status.upper()
        if status_up in {"INVALID", "CANCELED"}:
            self._runtime.record_broker_event(ts, "ORDER_EVENT_REJECT", str(getattr(order_event, "Message", "")), "error")

    def OnWarmupFinished(self) -> None:  # noqa: N802
        """Validate all subscribed symbols have data at warmup completion."""
        missing = sorted([symbol for symbol, received in self._received_consolidated.items() if not received])
        if missing:
            msg = f"WARMUP_NO_DATA symbols={','.join(missing)}"
            if hasattr(self, "Error"):
                self.Error(msg)
            elif hasattr(self, "Log"):
                self.Log(msg)
        elif hasattr(self, "Log"):
            self.Log(f"WARMUP_DATA_OK symbols={','.join(sorted(self._received_consolidated.keys()))}")

    def OnEndOfAlgorithm(self) -> None:  # noqa: N802
        """Log final summary for smoke acceptance checks."""
        if hasattr(self, "_runtime"):
            self._runtime.flush_live_artifacts()

        if not hasattr(self, "Log"):
            return
        signals = len(self._runtime.artifacts.signals)
        orders = len(self._runtime.artifacts.orders)
        regimes = len(self._runtime.artifacts.regime)
        self.Log(f"FXLE_SUMMARY signals={signals} orders={orders} regimes={regimes}")

    def _try_attach_lean_consolidator(self, canonical: str, symbol: Any) -> bool:
        if not hasattr(self, "SubscriptionManager"):
            return False
        try:
            consolidator = TradeBarConsolidator(timedelta(minutes=self._bar_interval_minutes))
            consolidator.DataConsolidated += self._on_data_consolidated  # type: ignore[attr-defined]
            self.SubscriptionManager.AddConsolidator(symbol, consolidator)  # type: ignore[attr-defined]
            self._lean_consolidators[canonical] = consolidator
            self._using_lean_consolidators = True
            return True
        except Exception as exc:
            if hasattr(self, "Log"):
                self.Log(f"FXLE_CONSOLIDATOR_FALLBACK symbol={canonical} reason={exc}")
            return False

    def _on_data_consolidated(self, _sender: Any, tradebar: Any) -> None:
        symbol_obj = getattr(tradebar, "Symbol", None)
        canonical = self._symbol_object_to_canonical.get(symbol_obj) or self._symbol_to_canonical.get(str(symbol_obj))
        if canonical is None:
            return
        end = getattr(tradebar, "EndTime", datetime.now(tz=UTC))
        start = end - timedelta(minutes=self._bar_interval_minutes)
        bar = Bar(
            symbol=canonical,
            start=start,
            end=end,
            open=float(tradebar.Open),
            high=float(tradebar.High),
            low=float(tradebar.Low),
            close=float(tradebar.Close),
            volume=float(getattr(tradebar, "Volume", 0.0)),
        )
        self._handle_consolidated_bar(bar)

    def _handle_consolidated_bar(self, bar: Bar) -> None:
        canonical = normalize_forex_pair(bar.symbol)
        self._received_consolidated[canonical] = True
        if hasattr(self, "Log"):
            self.Log(f"BAR_EMIT symbol={canonical} interval={self._bar_interval_minutes}m ts={bar.end.isoformat()}")
        if getattr(self, "IsWarmingUp", False):
            return
        result = self._runtime.on_consolidated_bar(bar)
        if result is not None:
            self._execute_approved_intents(result.approved)

    def _safe_set_holdings(self, symbol_obj: Any, target: float, context: str) -> bool:
        now = datetime.now(tz=UTC)
        try:
            self.SetHoldings(symbol_obj, target)
            if self._broker_error_active:
                self._runtime.set_broker_health(False, "ORDER_PATH_RECOVERED", timestamp=now)
                self._broker_error_active = False
            return True
        except Exception as exc:
            self._broker_error_active = True
            self._runtime.record_broker_event(now, "ORDER_SUBMIT_ERROR", f"{context}: {exc}", "error")
            self._runtime.set_broker_health(True, str(exc), timestamp=now)
            return False

    def _execute_approved_intents(self, approved: list[Any]) -> None:
        if not hasattr(self, "SetHoldings"):
            return

        for intent in approved:
            if intent.action == "close":
                if intent.symbol:
                    symbol_obj = self._canonical_to_symbol.get(intent.symbol)
                    if symbol_obj is not None:
                        self._safe_set_holdings(symbol_obj, 0.0, f"close:{intent.symbol}")
                if intent.pair:
                    left_obj = self._canonical_to_symbol.get(intent.pair[0])
                    right_obj = self._canonical_to_symbol.get(intent.pair[1])
                    if left_obj is not None:
                        self._safe_set_holdings(left_obj, 0.0, f"close:{intent.pair[0]}")
                    if right_obj is not None:
                        self._safe_set_holdings(right_obj, 0.0, f"close:{intent.pair[1]}")
                continue

            weight = float(intent.notional_pct_nav)
            if intent.engine == "trend" and intent.symbol:
                symbol_obj = self._canonical_to_symbol.get(intent.symbol)
                if symbol_obj is None:
                    continue
                signed = weight if intent.direction == "LONG" else -weight
                self._safe_set_holdings(symbol_obj, signed, f"trend:{intent.symbol}:{intent.direction}")
                continue

            if intent.engine == "pairs" and intent.pair:
                left_obj = self._canonical_to_symbol.get(intent.pair[0])
                right_obj = self._canonical_to_symbol.get(intent.pair[1])
                if left_obj is None or right_obj is None:
                    continue
                half = weight * 0.5
                if intent.direction == "LONG_SPREAD":
                    self._safe_set_holdings(left_obj, -half, f"pairs:{intent.pair[0]}:LONG_SPREAD")
                    self._safe_set_holdings(right_obj, half, f"pairs:{intent.pair[1]}:LONG_SPREAD")
                elif intent.direction == "SHORT_SPREAD":
                    self._safe_set_holdings(left_obj, half, f"pairs:{intent.pair[0]}:SHORT_SPREAD")
                    self._safe_set_holdings(right_obj, -half, f"pairs:{intent.pair[1]}:SHORT_SPREAD")

    def _read_parameter(self, name: str) -> str | None:
        if not hasattr(self, "GetParameter"):
            return None
        value = self.GetParameter(name)  # type: ignore[attr-defined]
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    @staticmethod
    def _parse_bool(value: str) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def _safe_git_sha(project_root: Path) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(project_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    def _build_live_metadata(
        self,
        *,
        project_root: Path,
        config_dir: Path,
        backtest_config_name: str,
        backtest_cfg: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        config_files = {
            "universe": config_dir / "universe.yaml",
            "pairs": config_dir / "pairs.yaml",
            "runtime": config_dir / "runtime.yaml",
            "pairs_policy": config_dir / "pairs_policy.yaml",
            "pairs_overrides": config_dir / "pairs_overrides.yaml",
            "regime": config_dir / "regime.yaml",
            "backtest": config_dir / backtest_config_name,
        }
        config_hashes = {
            name: self._sha256(path)
            for name, path in config_files.items()
            if path.exists()
        }

        run_manifest = {
            "run_id": self._runtime.live_run_id,
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "git_sha": self._safe_git_sha(project_root),
            "runtime_mode": self._runtime.runtime_cfg.execution_mode,
            "data_source": self._runtime.runtime_cfg.data_source,
            "config_hashes": config_hashes,
            "config_files": {name: str(path) for name, path in config_files.items() if path.exists()},
            "brokerage": self._runtime.runtime_cfg.brokerage,
            "oanda_environment": self._runtime.runtime_cfg.oanda_environment,
        }

        config_snapshot = {
            "universe": asdict(self._runtime.universe_cfg),
            "pairs": asdict(self._runtime.pairs_cfg),
            "runtime": asdict(self._runtime.runtime_cfg),
            "pairs_policy": asdict(self._runtime.pairs_policy_cfg),
            "regime": asdict(self._runtime.regime_cfg),
            "backtest": asdict(backtest_cfg),
        }
        return run_manifest, config_snapshot
