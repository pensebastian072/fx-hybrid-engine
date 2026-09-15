"""Runtime orchestration for consolidated FX bars."""

from __future__ import annotations

import hashlib
import subprocess
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from fx_lean_engine.config import (
    PairsPolicyConfig,
    load_pairs_config,
    load_pairs_policy_with_overrides,
    load_regime_config,
    load_runtime_config,
    load_universe_config,
)
from fx_lean_engine.config.models import PairsConfig, RegimeConfig, RuntimeConfig, UniverseConfig
from fx_lean_engine.data.feature_store import FeatureStore
from fx_lean_engine.data.health import BarHealthChecker
from fx_lean_engine.data.local_data import ensure_local_data_supported
from fx_lean_engine.engines.pairs import PairsEngine
from fx_lean_engine.engines.regime import RegimeOrchestrator
from fx_lean_engine.engines.regime_hmm import RegimeEngineHMM
from fx_lean_engine.engines.trend import TrendEngine
from fx_lean_engine.pairs.cointegration import fit_pair
from fx_lean_engine.pairs.universe import generate_candidate_pairs
from fx_lean_engine.pairs.validity import PairValidityManager
from fx_lean_engine.risk.caps import RiskCaps, RiskManager
from fx_lean_engine.storage import LiveArtifactSink
from fx_lean_engine.types import (
    Bar,
    PairStatus,
    PairsEngineFactory,
    PipelineArtifacts,
    PortfolioRiskState,
    RegimeEngineFactory,
    TrendEngineFactory,
    TradeIntent,
)

HEALTH_DATA_OK = "DATA_OK"
HEALTH_DATA_STALE = "DATA_STALE"
HEALTH_BROKER_DOWN = "BROKER_DOWN"


@dataclass(slots=True)
class RuntimeStepResult:
    """One runtime step output."""

    regime: dict[str, Any]
    signals: list[dict[str, Any]]
    intents: list[TradeIntent]
    approved: list[TradeIntent]
    rejected: list[dict[str, Any]]
    targets: list[dict[str, Any]]


class FxRuntimeEngine:
    """Main runtime orchestration engine."""

    def __init__(
        self,
        universe_cfg: UniverseConfig,
        pairs_cfg: PairsConfig,
        runtime_cfg: RuntimeConfig,
        pairs_policy_cfg: PairsPolicyConfig,
        regime_cfg: RegimeConfig | None = None,
        active_symbols: list[str] | None = None,
        pairs_lookback_override: int | None = None,
        pairs_engine_factory: PairsEngineFactory | None = None,
        trend_engine_factory: TrendEngineFactory | None = None,
        regime_engine_factory: RegimeEngineFactory | None = None,
        run_id: str | None = None,
    ):
        self.universe_cfg = universe_cfg
        self.pairs_cfg = pairs_cfg
        self.runtime_cfg = runtime_cfg
        self.pairs_policy_cfg = pairs_policy_cfg
        self.regime_cfg = regime_cfg or RegimeConfig()
        self.active_symbols = sorted({str(symbol).upper().strip() for symbol in (active_symbols or universe_cfg.pairs or [])})

        if self.runtime_cfg.data_source == "local":
            ensure_local_data_supported(self.runtime_cfg.local_data_dir)

        pair_tuples = [
            (pair[0], pair[1])
            for pair in pairs_cfg.pairs or []
            if pair[0] in self.active_symbols and pair[1] in self.active_symbols
        ]
        lookback = pairs_cfg.lookback_bars if pairs_lookback_override is None else int(pairs_lookback_override)

        self.feature_store = FeatureStore(warmup_bars=25)
        self.health_checker = BarHealthChecker(
            bar_interval_minutes=universe_cfg.consolidated_bar_minutes,
            gap_warn_threshold_minutes=runtime_cfg.gap_warn_threshold_minutes,
            strict_bar_ordering=runtime_cfg.strict_bar_ordering,
        )

        if pairs_engine_factory is None:
            self.pairs_engine = PairsEngine(
                pairs=pair_tuples,
                lookback_bars=lookback,
                entry_z=pairs_cfg.entry_z,
                exit_z=pairs_cfg.exit_z,
                max_holding_bars=pairs_cfg.max_holding_bars,
                notional_pct_nav=runtime_cfg.pairs_notional_pct_nav,
            )
        else:
            self.pairs_engine = pairs_engine_factory(
                pair_tuples,
                int(lookback),
                pairs_cfg,
                runtime_cfg,
                list(self.active_symbols),
            )

        if trend_engine_factory is None:
            self.trend_engine = TrendEngine(
                symbols=list(self.active_symbols),
                notional_pct_nav=runtime_cfg.trend_notional_pct_nav,
            )
        else:
            self.trend_engine = trend_engine_factory(list(self.active_symbols), runtime_cfg)

        if regime_engine_factory is None:
            self.regime_orchestrator = self._build_default_regime_engine()
        else:
            self.regime_orchestrator = regime_engine_factory(list(self.active_symbols), runtime_cfg)

        self.risk_manager = RiskManager(
            RiskCaps(
                max_gross_leverage=runtime_cfg.max_gross_leverage,
                max_pair_notional_pct_nav=runtime_cfg.max_pair_notional_pct_nav,
                max_symbol_notional_pct_nav=runtime_cfg.max_symbol_notional_pct_nav,
                max_open_pairs=runtime_cfg.max_open_pairs,
                max_open_trend_positions=runtime_cfg.max_open_trend_positions,
            )
        )
        self.risk_state = PortfolioRiskState()

        self.artifacts = PipelineArtifacts(
            signals=[],
            orders=[],
            equity_curve=[],
            regime=[],
            features=[],
            targets=[],
            bar_health=[],
            risk_events=[],
            pairs_candidates=[],
            pairs_scan=[],
            pair_state_events=[],
            pnl_by_pair=[],
            bars=[],
            fills=[],
            broker_events=[],
            regime_posteriors=[],
            regime_events=[],
            regime_hmm_params=None,
            regime_state_map=None,
            trade_training_rows=[],
            trade_analytics=[],
        )

        self._equity = 100000.0
        self._max_gross_exposure = 0.0
        self._warnings_count = 0
        self._errors_count = 0
        self._bar_index = 0
        self._turnover = 0.0

        self._open_pairs: set[tuple[str, str]] = set()
        self._open_trend_symbols: set[str] = set()
        self._pair_open_meta: dict[tuple[str, str], dict[str, float]] = {}
        self._pair_pnl: dict[tuple[str, str], dict[str, float]] = {}
        self._pair_latest_half_life: dict[tuple[str, str], float] = {}

        self._scan_history: dict[str, deque[float]] = {
            symbol: deque(maxlen=max(pairs_policy_cfg.lookback_bars + 5, 64)) for symbol in self.active_symbols
        }
        self._last_scan_date = None
        self._kill_switch_logged = False

        # Trade training context: symbol → entry metadata captured on open approval.
        self._open_trade_contexts: dict[str, dict[str, Any]] = {}
        # Bar index at which each symbol's trend position was opened (for hold_bars calc).
        self._open_trend_entry_bar: dict[str, int] = {}

        candidates, candidate_rows = generate_candidate_pairs(pairs_policy_cfg, self.active_symbols)
        self._candidate_pairs = candidates
        self.artifacts.pairs_candidates.extend(candidate_rows)

        self._validity_manager = PairValidityManager(
            policy=pairs_policy_cfg,
            bar_interval_minutes=universe_cfg.consolidated_bar_minutes,
        )

        self.live_run_id = str(run_id).strip() if run_id else f"{self.runtime_cfg.execution_mode}_{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}"
        self._live_sink = (
            LiveArtifactSink(self.runtime_cfg.live_output_root, self.live_run_id)
            if self.runtime_cfg.live_persistence_enabled
            else None
        )
        self._live_offsets: dict[str, int] = {
            "bars": 0,
            "features": 0,
            "signals": 0,
            "targets": 0,
            "orders": 0,
            "fills": 0,
            "equity_curve": 0,
            "regime": 0,
            "regime_posteriors": 0,
            "regime_events": 0,
            "risk_events": 0,
            "broker_events": 0,
        }
        self._live_manifest_payload: dict[str, Any] | None = None
        self._live_config_snapshot_payload: dict[str, Any] | None = None
        self._live_metadata_written = False

        self._health_state = HEALTH_DATA_OK
        self._broker_down = False
        self._last_update_timestamp: datetime | None = None

    def _build_default_regime_engine(self) -> Any:
        if self.regime_cfg.mode == "hmm":
            return RegimeEngineHMM(
                symbols=list(self.active_symbols),
                lookback_bars=self.regime_cfg.hmm_lookback_bars,
                retrain_frequency=self.regime_cfg.hmm_retrain_frequency,
                n_components=self.regime_cfg.hmm_n_components,
                covariance_type=self.regime_cfg.hmm_covariance_type,
                n_iter=self.regime_cfg.hmm_n_iter,
                random_state=self.regime_cfg.hmm_random_state,
                trend_prob_threshold=self.regime_cfg.trend_prob_threshold,
                chop_prob_threshold=self.regime_cfg.chop_prob_threshold,
                risk_off_prob_threshold=self.regime_cfg.risk_off_prob_threshold,
            )
        return RegimeOrchestrator(symbols=list(self.active_symbols))

    @staticmethod
    def _normalize_pair(pair: tuple[str, str]) -> tuple[str, str]:
        left = str(pair[0]).upper().strip()
        right = str(pair[1]).upper().strip()
        return (left, right) if left <= right else (right, left)

    @staticmethod
    def _symbol_or_pair_key(intent: TradeIntent) -> str:
        if intent.symbol:
            return intent.symbol
        if intent.pair:
            return "-".join(intent.pair)
        return ""

    def _record_risk_event(self, timestamp: datetime, event_type: str, reason: str, intent_id_or_symbol: str) -> None:
        row = {
            "timestamp": timestamp.isoformat(),
            "event_type": event_type,
            "reason": reason,
            "intent_id_or_symbol": intent_id_or_symbol,
        }
        self.artifacts.risk_events.append(row)

    def _record_broker_event(self, timestamp: datetime, event_type: str, detail: str, severity: str = "warn") -> None:
        self.artifacts.broker_events.append(
            {
                "timestamp": timestamp.isoformat(),
                "event_type": str(event_type),
                "detail": str(detail),
                "severity": str(severity),
            }
        )

    def record_broker_event(self, timestamp: datetime, event_type: str, detail: str, severity: str = "warn") -> None:
        """Public hook for LEAN algorithm broker/error events."""
        self._record_broker_event(timestamp, event_type, detail, severity)
        self._persist_live_artifacts()

    def record_fill(
        self,
        timestamp: datetime,
        *,
        symbol: str,
        status: str,
        order_id: str = "",
        fill_quantity: float = 0.0,
        fill_price: float = 0.0,
        message: str = "",
    ) -> None:
        """Public hook for LEAN order fills/events."""
        self.artifacts.fills.append(
            {
                "timestamp": timestamp.isoformat(),
                "order_id": str(order_id),
                "symbol": str(symbol).upper().strip(),
                "status": str(status),
                "fill_quantity": float(fill_quantity),
                "fill_price": float(fill_price),
                "message": str(message),
            }
        )
        self._persist_live_artifacts()

    def set_broker_health(self, down: bool, reason: str = "", timestamp: datetime | None = None) -> None:
        """Set broker connectivity/health state."""
        ts = timestamp or datetime.now(tz=UTC)
        self._broker_down = bool(down)
        if self._broker_down:
            self._record_broker_event(ts, "BROKER_DOWN", reason or "BROKER_CONNECTIVITY_ERROR", "error")
        else:
            self._record_broker_event(ts, "BROKER_RECOVERED", reason or "BROKER_CONNECTIVITY_OK", "info")
        self._persist_live_artifacts()

    def set_live_metadata(
        self,
        run_manifest: dict[str, Any],
        config_snapshot: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> None:
        """Set live/paper manifest and config snapshot payload."""
        self._live_manifest_payload = dict(run_manifest)
        self._live_config_snapshot_payload = dict(config_snapshot)
        if self._live_sink is not None:
            self._live_sink.write_run_metadata(
                timestamp or datetime.now(tz=UTC),
                run_manifest=self._live_manifest_payload,
                config_snapshot=self._live_config_snapshot_payload,
            )
            self._live_metadata_written = True

    def _persist_live_artifacts(self) -> None:
        if self._live_sink is None:
            return

        parquet_artifacts = [
            "bars",
            "features",
            "signals",
            "targets",
            "orders",
            "fills",
            "equity_curve",
            "regime",
            "regime_posteriors",
            "regime_events",
            "risk_events",
        ]
        for name in parquet_artifacts:
            rows = list(getattr(self.artifacts, name))
            start = self._live_offsets.get(name, 0)
            if start < len(rows):
                self._live_sink.append_parquet_rows(name, rows[start:])
                self._live_offsets[name] = len(rows)

        broker_rows = self.artifacts.broker_events
        broker_start = self._live_offsets.get("broker_events", 0)
        if broker_start < len(broker_rows):
            self._live_sink.append_jsonl_rows("broker_events", broker_rows[broker_start:])
            self._live_offsets["broker_events"] = len(broker_rows)

        if (
            not self._live_metadata_written
            and self._live_manifest_payload is not None
            and self._live_config_snapshot_payload is not None
        ):
            self._live_sink.write_run_metadata(
                datetime.now(tz=UTC),
                run_manifest=self._live_manifest_payload,
                config_snapshot=self._live_config_snapshot_payload,
            )
            self._live_metadata_written = True

    def flush_live_artifacts(self) -> None:
        """Flush all buffered live/paper artifacts to sink."""
        self._persist_live_artifacts()

    @property
    def last_update_timestamp(self) -> datetime | None:
        """Return the timestamp of the last successfully processed bar, or None if no bar has been processed."""
        return self._last_update_timestamp

    def _update_health_state(self, timestamp: datetime) -> str:
        if self._broker_down:
            new_state = HEALTH_BROKER_DOWN
        else:
            last_seen = self.health_checker.snapshot_last_timestamps()
            if len(last_seen) < len(self.active_symbols):
                new_state = HEALTH_DATA_STALE
            else:
                max_age_minutes = max(
                    max((timestamp - ts).total_seconds() / 60.0, 0.0)
                    for ts in last_seen.values()
                )
                new_state = HEALTH_DATA_STALE if max_age_minutes > float(self.runtime_cfg.data_stale_minutes) else HEALTH_DATA_OK

        if new_state != self._health_state:
            self._record_broker_event(timestamp, "HEALTH_STATE", f"{self._health_state}->{new_state}", "warn")
            if new_state != HEALTH_DATA_OK:
                self._record_risk_event(timestamp, "HEALTH_STATE", new_state, "GLOBAL")
        self._health_state = new_state
        return new_state

    def _update_scan_history(self, symbol: str, close: float) -> None:
        key = str(symbol).upper().strip()
        if key in self._scan_history:
            self._scan_history[key].append(float(close))

    def _should_scan(self, timestamp: datetime) -> bool:
        if not self.runtime_cfg.phase2_pairs_gating_enabled:
            return False
        if self._last_scan_date is None:
            return True
        return timestamp.date() > self._last_scan_date

    def _run_daily_scan(self, timestamp: datetime) -> None:
        if not self._candidate_pairs:
            return

        fits = []
        insufficient_rows: list[dict[str, str]] = []
        lookback = self.pairs_policy_cfg.lookback_bars
        for pair in self._candidate_pairs:
            left, right = pair
            left_hist = np.asarray(list(self._scan_history.get(left, [])), dtype=float)
            right_hist = np.asarray(list(self._scan_history.get(right, [])), dtype=float)
            if left_hist.size < lookback or right_hist.size < lookback:
                insufficient_rows.append(
                    {
                        "timestamp": timestamp.isoformat(),
                        "pair": f"{left}-{right}",
                        "beta": "",
                        "p_value": "",
                        "spread_std": "",
                        "half_life": "",
                        "beta_drift": "",
                        "spread_last_z": "",
                        "pair_status": str(PairStatus.WATCH),
                        "status_reason": "INSUFFICIENT_DATA",
                        "disabled_until": "",
                    }
                )
                continue

            y = np.log(np.maximum(left_hist, 1e-12))
            x = np.log(np.maximum(right_hist, 1e-12))
            fit = fit_pair(y=y, x=x, lookback=lookback, pair=pair, timestamp=timestamp)
            fits.append(fit)
            canonical = self._normalize_pair(pair)
            self._pair_latest_half_life[canonical] = float(fit.half_life)

        scan_rows, state_events = self._validity_manager.apply_scan(fits)
        self.artifacts.pairs_scan.extend(scan_rows)
        self.artifacts.pairs_scan.extend(insufficient_rows)
        self.artifacts.pair_state_events.extend(state_events)
        self._last_scan_date = timestamp.date()

    def _pair_status_map_for_engine(self) -> dict[tuple[str, str], str]:
        if not self.runtime_cfg.phase2_pairs_gating_enabled:
            out: dict[tuple[str, str], str] = {}
            for pair in self.pairs_engine.pairs:
                out[pair] = str(PairStatus.TRADABLE)
                out[(pair[1], pair[0])] = str(PairStatus.TRADABLE)
            return out

        status_map = self._validity_manager.get_status_map()
        out: dict[tuple[str, str], str] = {}
        for pair in self._candidate_pairs:
            status = status_map.get(pair, str(PairStatus.WATCH))
            out[pair] = status
            out[(pair[1], pair[0])] = status
        return out

    def _apply_regime_weights(self, intents: list[TradeIntent], trend_weight: float, pairs_weight: float) -> list[TradeIntent]:
        out: list[TradeIntent] = []
        for intent in intents:
            weight = trend_weight if intent.engine == "trend" else pairs_weight
            notional = float(intent.notional_pct_nav)
            if intent.action == "open":
                notional *= float(weight)
            out.append(
                TradeIntent(
                    engine=intent.engine,
                    action=intent.action,
                    symbol=intent.symbol,
                    pair=intent.pair,
                    direction=intent.direction,
                    notional_pct_nav=notional,
                    confidence=float(intent.confidence),
                    reason=intent.reason,
                    pair_status=intent.pair_status,
                )
            )
        return out

    def _force_close_intents(self) -> list[TradeIntent]:
        closes: list[TradeIntent] = []
        for symbol in sorted(self._open_trend_symbols):
            closes.append(
                TradeIntent(
                    engine="trend",
                    action="close",
                    symbol=symbol,
                    pair=None,
                    direction="EXIT",
                    notional_pct_nav=self.runtime_cfg.trend_notional_pct_nav,
                    confidence=1.0,
                    reason="KILL_SWITCH_FORCE_EXIT",
                )
            )
        for pair in sorted(self._open_pairs):
            closes.append(
                TradeIntent(
                    engine="pairs",
                    action="close",
                    symbol=None,
                    pair=pair,
                    direction="EXIT",
                    notional_pct_nav=self.runtime_cfg.pairs_notional_pct_nav,
                    confidence=1.0,
                    reason="KILL_SWITCH_FORCE_EXIT",
                    pair_status=str(PairStatus.DISABLED),
                )
            )
        return closes

    @staticmethod
    def _intent_key(intent: TradeIntent) -> tuple[str, str | None, tuple[str, str] | None, str, str]:
        return (
            intent.engine,
            intent.symbol,
            intent.pair,
            intent.action,
            intent.direction,
        )

    def _apply_position_book(self, intent: TradeIntent, pair_signal_z: dict[tuple[str, str], float]) -> None:
        if intent.engine == "trend" and intent.symbol:
            symbol = intent.symbol.upper()
            if intent.action == "open":
                self._open_trend_symbols.add(symbol)
            elif intent.action == "close":
                self._open_trend_symbols.discard(symbol)
            # Keep TrendEngine's internal position book in sync.
            notify_fn = getattr(self.trend_engine, "notify_fill", None)
            if callable(notify_fn):
                notify_fn(symbol, intent.action, intent.direction)
            return

        if intent.engine == "pairs" and intent.pair:
            pair = self._normalize_pair((intent.pair[0], intent.pair[1]))
            if intent.action == "open":
                self._open_pairs.add(pair)
                entry_abs_z = abs(float(pair_signal_z.get(pair, 0.0)))
                self._pair_open_meta[pair] = {
                    "entry_abs_z": entry_abs_z,
                    "open_bar": float(self._bar_index),
                    "open_half_life": float(self._pair_latest_half_life.get(pair, float("inf"))),
                }
            elif intent.action == "close":
                self._open_pairs.discard(pair)
                meta = self._pair_open_meta.pop(pair, None)
                if meta is None:
                    return
                exit_abs_z = abs(float(pair_signal_z.get(pair, 0.0)))
                pnl_proxy = float(meta["entry_abs_z"] - exit_abs_z)
                bars_held = max(float(self._bar_index) - float(meta["open_bar"]), 0.0)
                half_life = float(meta.get("open_half_life", float("inf")))
                holding_vs_half_life = 0.0
                if np.isfinite(half_life) and half_life > 1e-12:
                    holding_vs_half_life = bars_held / half_life

                agg = self._pair_pnl.setdefault(
                    pair,
                    {
                        "pnl_proxy": 0.0,
                        "trades": 0.0,
                        "holding_bars": 0.0,
                        "holding_vs_half_life_sum": 0.0,
                    },
                )
                agg["pnl_proxy"] += pnl_proxy
                agg["trades"] += 1.0
                agg["holding_bars"] += bars_held
                agg["holding_vs_half_life_sum"] += holding_vs_half_life

    def _enforce_time_stop_disable(self, timestamp: datetime) -> list[TradeIntent]:
        if not self.runtime_cfg.phase2_pairs_gating_enabled:
            return []

        forced: list[TradeIntent] = []
        for pair in sorted(self._open_pairs):
            meta = self._pair_open_meta.get(pair, {})
            open_bar = float(meta.get("open_bar", self._bar_index))
            bars_held = max(float(self._bar_index) - open_bar, 0.0)
            half_life = float(meta.get("open_half_life", self._pair_latest_half_life.get(pair, float("inf"))))
            if not np.isfinite(half_life) or half_life <= 1e-12:
                continue
            max_bars = max(float(self.pairs_policy_cfg.time_stop_half_life_mult) * half_life, 1.0)
            if bars_held <= max_bars:
                continue

            state_events = self._validity_manager.force_disable(pair, timestamp, reason="TIME_STOP_BREAKDOWN")
            self.artifacts.pair_state_events.extend(state_events)
            self._record_risk_event(timestamp, "PAIR_DISABLE", "TIME_STOP_HALF_LIFE", f"{pair[0]}-{pair[1]}")
            forced.append(
                TradeIntent(
                    engine="pairs",
                    action="close",
                    symbol=None,
                    pair=pair,
                    direction="EXIT",
                    notional_pct_nav=self.runtime_cfg.pairs_notional_pct_nav,
                    confidence=1.0,
                    reason="PAIR_TIME_STOP_EXIT",
                    pair_status=str(PairStatus.DISABLED),
                )
            )

        return forced

    # ------------------------------------------------------------------
    # Cross-engine alignment gate (Task 3)
    # ------------------------------------------------------------------

    def _apply_alignment_gate(
        self,
        trend_intents: list[TradeIntent],
        pair_intents: list[TradeIntent],
        timestamp: datetime,
    ) -> tuple[list[TradeIntent], list[dict[str, Any]]]:
        """Gate trend opens: only pass through when a pairs open exists for the same symbol.

        Non-open intents (close, reversal) are never gated.
        Trend opens below ``alignment_min_confidence`` are always gated when the
        flag is active.

        Returns:
            (filtered_trend_intents, blocked_items) where blocked_items have the
            same shape as items in the main ``blocked`` list.
        """
        aligned_symbols: set[str] = set()
        for pi in pair_intents:
            if pi.action == "open" and pi.pair:
                aligned_symbols.add(pi.pair[0].upper())
                aligned_symbols.add(pi.pair[1].upper())

        passed: list[TradeIntent] = []
        blocked: list[dict[str, Any]] = []

        for ti in trend_intents:
            if ti.action != "open":
                # Close / reversal intents always pass through.
                passed.append(ti)
                continue

            sym = (ti.symbol or "").upper()
            if sym not in aligned_symbols:
                reason = "ALIGNMENT_GATE"
            elif float(ti.confidence) < float(self.runtime_cfg.alignment_min_confidence):
                reason = "ALIGNMENT_LOW_CONFIDENCE"
            else:
                passed.append(ti)
                continue

            self._record_risk_event(timestamp, "BLOCK_OPEN", reason, sym)
            blocked.append({"intent": asdict(ti), "reason": reason})

        return passed, blocked

    # ------------------------------------------------------------------
    # Training row emission (Task 2)
    # ------------------------------------------------------------------

    def _emit_training_row(
        self,
        ctx: dict[str, Any],
        exit_timestamp: datetime,
        exit_price: float,
        exit_reason: str,
    ) -> None:
        """Append one completed-trade training row to artifacts.trade_training_rows."""
        entry_price = float(ctx.get("entry_price", 0.0))
        if entry_price == 0.0:
            return

        direction = str(ctx.get("direction", "LONG"))
        if direction == "LONG":
            realized_pnl_pct = (exit_price - entry_price) / entry_price
        else:
            realized_pnl_pct = (entry_price - exit_price) / entry_price

        entry_bar = int(ctx.get("entry_bar_index", 0))
        hold_bars = max(self._bar_index - entry_bar, 0)
        is_win = 1 if realized_pnl_pct > 0 else 0

        row: dict[str, Any] = {
            "entry_timestamp": ctx.get("entry_timestamp", ""),
            "exit_timestamp": exit_timestamp.isoformat(),
            "symbol": ctx.get("symbol", ""),
            "engine_source": ctx.get("engine_source", "trend"),
            "direction": direction,
            "entry_price": float(entry_price),
            "exit_price": float(exit_price),
            "hold_bars": int(hold_bars),
            "entry_regime": ctx.get("entry_regime", ""),
            "entry_regime_prob_trend": float(ctx.get("entry_regime_prob_trend", 0.0)),
            "entry_regime_prob_chop": float(ctx.get("entry_regime_prob_chop", 0.0)),
            "entry_regime_prob_risk_off": float(ctx.get("entry_regime_prob_risk_off", 0.0)),
            "realized_pnl_pct": float(realized_pnl_pct),
            "is_win": int(is_win),
            "exit_reason": str(exit_reason),
        }
        # Carry forward any entry feature values stored in context.
        for k, v in ctx.items():
            if k.startswith("feat_"):
                row[k] = v

        self.artifacts.trade_training_rows.append(row)

    def _record_targets(self, timestamp: datetime, intents: list[TradeIntent]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not intents:
            rows.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "engine": "none",
                    "action": "hold",
                    "symbol": "",
                    "pair": "",
                    "direction": "FLAT",
                    "target_notional_pct_nav": 0.0,
                    "pair_status": "",
                    "reason": "NO_INTENTS",
                }
            )
        for intent in intents:
            row = {
                "timestamp": timestamp.isoformat(),
                "engine": intent.engine,
                "action": intent.action,
                "symbol": intent.symbol or "",
                "pair": "-".join(intent.pair) if intent.pair else "",
                "direction": intent.direction,
                "target_notional_pct_nav": float(intent.notional_pct_nav),
                "pair_status": intent.pair_status or "",
                "reason": intent.reason,
            }
            rows.append(row)
        self.artifacts.targets.extend(rows)
        return rows

    def on_consolidated_bar(self, bar: Bar) -> RuntimeStepResult | None:
        """Update runtime state for one consolidated bar."""
        self._bar_index += 1
        self._last_update_timestamp = bar.end
        self.artifacts.bars.append(
            {
                "timestamp": bar.end.isoformat(),
                "symbol": str(bar.symbol).upper().strip(),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
                "interval_minutes": int(self.universe_cfg.consolidated_bar_minutes),
            }
        )

        accept, health_events = self.health_checker.check(bar.symbol, bar.end)
        for event in health_events:
            row = BarHealthChecker.event_row(event)
            self.artifacts.bar_health.append(row)
            if event.severity == "warn":
                self._warnings_count += 1
            elif event.severity == "error":
                self._errors_count += 1

        if not accept:
            self._persist_live_artifacts()
            return None

        self._update_scan_history(bar.symbol, float(bar.close))

        vector = self.feature_store.update(bar)
        if vector is not None:
            row = asdict(vector)
            row["timestamp"] = row["timestamp"].isoformat()
            self.artifacts.features.append(row)

        snapshot = self.feature_store.latest_close_snapshot()
        feature_snapshot = self.feature_store.latest_feature_snapshot()
        health_state = self._update_health_state(bar.end)
        if len(snapshot) < len(self.active_symbols):
            self._persist_live_artifacts()
            return None

        if self._should_scan(bar.end):
            self._run_daily_scan(bar.end)

        time_stop_intents = self._enforce_time_stop_disable(bar.end)
        pair_status_map = self._pair_status_map_for_engine()

        regime = self.regime_orchestrator.update(snapshot, feature_snapshot=feature_snapshot, timestamp=bar.end)
        regime_row = asdict(regime)
        regime_row["timestamp"] = bar.end.isoformat()
        self.artifacts.regime.append(regime_row)

        drain_fn = getattr(self.regime_orchestrator, "drain_artifacts", None)
        if callable(drain_fn):
            drained = drain_fn() or {}
            self.artifacts.regime_posteriors.extend(drained.get("regime_posteriors", []) or [])
            self.artifacts.regime_events.extend(drained.get("regime_events", []) or [])
            if drained.get("regime_hmm_params") is not None:
                self.artifacts.regime_hmm_params = drained.get("regime_hmm_params")
            if drained.get("regime_state_map") is not None:
                self.artifacts.regime_state_map = drained.get("regime_state_map")

        pair_signals, pair_intents = self.pairs_engine.update(snapshot, bar.end, pair_status_map=pair_status_map)
        trend_signals, trend_intents = self.trend_engine.update(snapshot)

        signal_rows: list[dict[str, Any]] = []
        pair_signal_z: dict[tuple[str, str], float] = {}
        for signal in pair_signals:
            payload = asdict(signal)
            payload["engine"] = "pairs"
            payload["timestamp"] = bar.end.isoformat()
            payload["pair"] = "-".join(payload["pair"])
            signal_rows.append(payload)
            pair_signal_z[self._normalize_pair(signal.pair)] = float(signal.zscore)
        for signal in trend_signals:
            payload = asdict(signal)
            payload["engine"] = "trend"
            payload["timestamp"] = bar.end.isoformat()
            signal_rows.append(payload)

        self.artifacts.signals.extend(signal_rows)

        # Apply cross-engine alignment gate before regime weighting (Task 3).
        alignment_blocked: list[dict[str, Any]] = []
        if self.runtime_cfg.require_signal_alignment:
            trend_intents, alignment_blocked = self._apply_alignment_gate(
                trend_intents, pair_intents, bar.end
            )

        intents = self._apply_regime_weights(pair_intents + trend_intents, regime.trend_weight, regime.pairs_weight)
        intents.extend(time_stop_intents)
        targets = self._record_targets(bar.end, intents)

        blocked: list[dict[str, Any]] = list(alignment_blocked)
        filtered_intents: list[TradeIntent] = []

        kill_switch_active = bool(self.runtime_cfg.kill_switch_enabled)
        if kill_switch_active and not self._kill_switch_logged:
            self._record_risk_event(bar.end, "KILL_SWITCH", self.runtime_cfg.kill_switch_reason, "GLOBAL")
            self._kill_switch_logged = True

        for intent in intents:
            symbol_key = self._symbol_or_pair_key(intent)
            if kill_switch_active and intent.action == "open":
                blocked.append({"intent": asdict(intent), "reason": "KILL_SWITCH_ACTIVE"})
                self._record_risk_event(bar.end, "BLOCK_OPEN", "KILL_SWITCH_ACTIVE", symbol_key)
                continue
            if self.runtime_cfg.block_new_entries and intent.action == "open":
                blocked.append({"intent": asdict(intent), "reason": "BLOCK_NEW_ENTRIES"})
                self._record_risk_event(bar.end, "BLOCK_OPEN", "BLOCK_NEW_ENTRIES", symbol_key)
                continue
            if health_state in {HEALTH_DATA_STALE, HEALTH_BROKER_DOWN} and intent.action == "open":
                reason = f"HEALTH_STATE_{health_state}"
                blocked.append({"intent": asdict(intent), "reason": reason})
                self._record_risk_event(bar.end, "BLOCK_OPEN", reason, symbol_key)
                continue
            if intent.action == "open" and intent.notional_pct_nav <= 0:
                blocked.append({"intent": asdict(intent), "reason": "REGIME_WEIGHT_ZERO"})
                continue
            filtered_intents.append(intent)

        if kill_switch_active:
            filtered_intents.extend(self._force_close_intents())

        dedup: dict[tuple[str, str | None, tuple[str, str] | None, str, str], TradeIntent] = {}
        for intent in filtered_intents:
            dedup[self._intent_key(intent)] = intent
        filtered_intents = list(dedup.values())

        approved: list[TradeIntent] = []
        rejected: list[dict[str, Any]] = []

        for intent in filtered_intents:
            decision = self.risk_manager.evaluate_intent(intent, self.risk_state)
            if decision.approved:
                self.risk_manager.apply_approved_intent(intent, self.risk_state)
                approved.append(intent)
                self._apply_position_book(intent, pair_signal_z)

                # Capture entry context or emit training row on close (Task 2).
                if intent.engine == "trend" and intent.symbol:
                    sym = intent.symbol.upper()
                    if intent.action == "open":
                        fv = (feature_snapshot or {}).get(sym)
                        feat_dict: dict[str, Any] = {}
                        if fv is not None:
                            try:
                                raw = asdict(fv)
                                feat_dict = {
                                    f"feat_{k}": v
                                    for k, v in raw.items()
                                    if k not in {"symbol", "timestamp"}
                                    and not isinstance(v, (dict, list))
                                }
                            except Exception:
                                pass
                        self._open_trade_contexts[sym] = {
                            "entry_timestamp": bar.end.isoformat(),
                            "symbol": sym,
                            "engine_source": intent.engine,
                            "direction": intent.direction,
                            "entry_price": float(snapshot.get(sym, 0.0)),
                            "entry_bar_index": int(self._bar_index),
                            "entry_regime": str(regime_row.get("state", "")),
                            "entry_regime_prob_trend": float(regime_row.get("p_trend", 0.0)),
                            "entry_regime_prob_chop": float(regime_row.get("p_chop", 0.0)),
                            "entry_regime_prob_risk_off": float(regime_row.get("p_risk_off", 0.0)),
                            **feat_dict,
                        }
                    elif intent.action == "close":
                        ctx = self._open_trade_contexts.pop(sym, None)
                        if ctx is not None:
                            self._emit_training_row(
                                ctx,
                                bar.end,
                                float(snapshot.get(sym, 0.0)),
                                intent.reason,
                            )
            else:
                rejected.append({"intent": asdict(intent), "reason": decision.reason})
                self._record_risk_event(
                    bar.end,
                    "RISK_REJECT",
                    decision.reason,
                    self._symbol_or_pair_key(intent),
                )

        rejected.extend(blocked)

        for intent in approved:
            row = asdict(intent)
            row["status"] = "approved"
            row["timestamp"] = bar.end.isoformat()
            self.artifacts.orders.append(row)
            self._turnover += abs(float(intent.notional_pct_nav))

        for item in rejected:
            row = dict(item["intent"])
            row["status"] = "rejected"
            row["risk_reason"] = item["reason"]
            row["timestamp"] = bar.end.isoformat()
            self.artifacts.orders.append(row)

        self._max_gross_exposure = max(self._max_gross_exposure, float(self.risk_state.gross_leverage))

        self._equity += float(len(approved)) - float(len(rejected)) * 0.05
        self.artifacts.equity_curve.append(
            {
                "timestamp": bar.end.isoformat(),
                "equity": self._equity,
                "approved_orders": len(approved),
                "rejected_orders": len(rejected),
                "regime": regime.state,
                "gross_exposure": float(self.risk_state.gross_leverage),
                "health_state": health_state,
            }
        )

        self._persist_live_artifacts()
        return RuntimeStepResult(
            regime=regime_row,
            signals=signal_rows,
            intents=intents,
            approved=approved,
            rejected=rejected,
            targets=targets,
        )

    def build_pair_pnl_rows(self) -> list[dict[str, Any]]:
        """Return pair-level pnl proxy metrics."""
        rows: list[dict[str, Any]] = []
        all_pairs = sorted(set(self._pair_pnl.keys()).union(set(self._candidate_pairs)))
        for pair in all_pairs:
            stats = self._pair_pnl.get(
                pair,
                {
                    "pnl_proxy": 0.0,
                    "trades": 0.0,
                    "holding_bars": 0.0,
                    "holding_vs_half_life_sum": 0.0,
                },
            )
            trades = max(float(stats["trades"]), 0.0)
            avg_hold = float(stats["holding_bars"]) / trades if trades > 0 else 0.0
            avg_hold_vs_half_life = float(stats["holding_vs_half_life_sum"]) / trades if trades > 0 else 0.0
            pair_name = f"{pair[0]}-{pair[1]}"
            scan_rows = [row for row in self.artifacts.pairs_scan if str(row.get("pair", "")) == pair_name]
            tradable = len([row for row in scan_rows if str(row.get("pair_status", "")) == str(PairStatus.TRADABLE)])
            tradable_pct = float(tradable) / float(len(scan_rows)) if scan_rows else 0.0
            disable_events = len(
                [
                    row
                    for row in self.artifacts.pair_state_events
                    if str(row.get("pair", "")) == pair_name and str(row.get("to", "")) == str(PairStatus.DISABLED)
                ]
            )
            reenable_events = len(
                [
                    row
                    for row in self.artifacts.pair_state_events
                    if str(row.get("pair", "")) == pair_name and str(row.get("to", "")) == str(PairStatus.TRADABLE)
                ]
            )
            rows.append(
                {
                    "pair": pair_name,
                    "pnl_proxy": float(stats["pnl_proxy"]),
                    "trades": int(trades),
                    "avg_holding_bars": float(avg_hold),
                    "pct_time_tradable": float(tradable_pct),
                    "disable_events": int(disable_events),
                    "reenable_events": int(reenable_events),
                    "avg_holding_vs_half_life": float(avg_hold_vs_half_life),
                }
            )
        return rows

    def build_trade_analytics_rows(self) -> list[dict[str, Any]]:
        """Compute per-trade analytics from approved orders and bar price paths (Task 5).

        Matches approved ``action="open"`` and ``action="close"`` orders by
        ``engine|symbol`` key (FIFO) and computes realized MFE, MAE, entry
        efficiency, win/loss and exit-reason stats from the OHLCV bar path
        stored in ``artifacts.bars``.

        Side-effect: sets ``self.artifacts.trade_analytics`` to the result.
        Returns the per-trade rows list.
        """
        approved = [row for row in self.artifacts.orders if str(row.get("status")) == "approved"]

        # Index bars by symbol for fast price lookups.
        bar_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for bar_row in self.artifacts.bars:
            sym = str(bar_row.get("symbol", "")).upper()
            bar_by_symbol.setdefault(sym, []).append(bar_row)

        def _close_at(sym: str, ts_str: str) -> float:
            for b in bar_by_symbol.get(sym, []):
                if str(b.get("timestamp", "")) == ts_str:
                    return float(b.get("close", 0.0))
            return 0.0

        def _bars_between(sym: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
            return [
                b
                for b in bar_by_symbol.get(sym, [])
                if start_ts <= str(b.get("timestamp", "")) <= end_ts
            ]

        # Queue open orders per engine|symbol, match closes FIFO.
        open_queues: dict[str, list[dict[str, Any]]] = {}
        trade_rows: list[dict[str, Any]] = []

        for order in sorted(approved, key=lambda r: str(r.get("timestamp", ""))):
            sym = str(order.get("symbol", "")).upper()
            engine = str(order.get("engine", ""))
            action = str(order.get("action", ""))
            ts = str(order.get("timestamp", ""))
            key = f"{engine}|{sym}"

            if not sym or not engine:
                continue

            if action == "open":
                open_queues.setdefault(key, []).append(order)
            elif action == "close":
                queue = open_queues.get(key, [])
                if not queue:
                    continue
                open_order = queue.pop(0)
                open_ts = str(open_order.get("timestamp", ""))
                entry_price = _close_at(sym, open_ts)
                exit_price = _close_at(sym, ts)
                open_dir = str(open_order.get("direction", "LONG"))

                path = _bars_between(sym, open_ts, ts)
                highs = [float(b["high"]) for b in path if b.get("high") is not None]
                lows = [float(b["low"]) for b in path if b.get("low") is not None]

                mfe = mae = entry_efficiency = realized_pnl_pct = 0.0
                if entry_price > 0 and path:
                    if open_dir == "LONG":
                        mfe = max(0.0, (max(highs) - entry_price) / entry_price) if highs else 0.0
                        mae = max(0.0, (entry_price - min(lows)) / entry_price) if lows else 0.0
                        realized_pnl_pct = (exit_price - entry_price) / entry_price if exit_price > 0 else 0.0
                    else:
                        mfe = max(0.0, (entry_price - min(lows)) / entry_price) if lows else 0.0
                        mae = max(0.0, (max(highs) - entry_price) / entry_price) if highs else 0.0
                        realized_pnl_pct = (entry_price - exit_price) / entry_price if exit_price > 0 else 0.0
                    entry_efficiency = min(max(realized_pnl_pct / mfe, 0.0), 1.0) if mfe > 1e-12 else 0.0

                is_win = 1 if realized_pnl_pct > 0 else 0
                trade_rows.append(
                    {
                        "entry_timestamp": open_ts,
                        "exit_timestamp": ts,
                        "symbol": sym,
                        "engine_source": engine,
                        "direction": open_dir,
                        "entry_price": float(entry_price),
                        "exit_price": float(exit_price),
                        "mfe": float(mfe),
                        "mae": float(mae),
                        "entry_efficiency": float(entry_efficiency),
                        "realized_pnl_pct": float(realized_pnl_pct),
                        "is_win": int(is_win),
                        "exit_reason": str(order.get("reason", "")),
                        "hold_bars": int(len(path)),
                    }
                )

        self.artifacts.trade_analytics = trade_rows
        return trade_rows

    def build_metrics(self, run_id: str, start: str, end: str, resolution: str) -> dict[str, Any]:
        """Build metrics.json payload."""
        approved_orders = [row for row in self.artifacts.orders if str(row.get("status")) == "approved"]
        trades_count = len([row for row in approved_orders if str(row.get("action")) in {"open", "close"}])
        pair_rows = self.build_pair_pnl_rows()
        self.artifacts.pnl_by_pair = pair_rows
        avg_holding = (
            float(np.mean([row["avg_holding_bars"] for row in pair_rows])) if pair_rows else 0.0
        )

        analytics_rows = self.build_trade_analytics_rows()
        win_rate = float(np.mean([r["is_win"] for r in analytics_rows])) if analytics_rows else 0.0
        avg_mae = float(np.mean([r["mae"] for r in analytics_rows])) if analytics_rows else 0.0
        avg_mfe = float(np.mean([r["mfe"] for r in analytics_rows])) if analytics_rows else 0.0
        avg_entry_eff = float(np.mean([r["entry_efficiency"] for r in analytics_rows])) if analytics_rows else 0.0

        by_engine: dict[str, list[int]] = {}
        exit_reason_distribution: dict[str, int] = {}
        for r in analytics_rows:
            by_engine.setdefault(str(r.get("engine_source", "")), []).append(int(r["is_win"]))
            reason = str(r.get("exit_reason", ""))
            exit_reason_distribution[reason] = exit_reason_distribution.get(reason, 0) + 1

        win_rate_by_signal_type = {k: float(np.mean(v)) for k, v in by_engine.items()}
        trade_attribution = {k: float(np.mean(v)) for k, v in by_engine.items()}

        metrics = {
            "run_id": run_id,
            "symbols": list(self.active_symbols),
            "resolution": resolution,
            "bar_interval_minutes": int(self.universe_cfg.consolidated_bar_minutes),
            "start": start,
            "end": end,
            "signals_count": int(len(self.artifacts.signals)),
            "orders_count": int(len(self.artifacts.orders)),
            "trades_count": int(trades_count),
            "max_gross_exposure": float(self._max_gross_exposure),
            "avg_holding_bars": float(avg_holding),
            "turnover": float(self._turnover),
            "warnings_count": int(self._warnings_count),
            "errors_count": int(self._errors_count),
            "last_update_at": self._last_update_timestamp.isoformat() if self._last_update_timestamp is not None else None,
            "feature_counters": self.feature_store.counters(),
            # Trade analytics (Task 5).
            "trade_analytics_rows": int(len(analytics_rows)),
            "win_rate": float(win_rate),
            "average_adverse_excursion": float(avg_mae),
            "average_mfe": float(avg_mfe),
            "entry_efficiency": float(avg_entry_eff),
            "win_rate_by_signal_type": win_rate_by_signal_type,
            "exit_reason_distribution": exit_reason_distribution,
            "trade_attribution": trade_attribution,
        }
        return metrics



def _default_pairs_policy_from_pairs_cfg(pairs_cfg: PairsConfig) -> PairsPolicyConfig:
    return PairsPolicyConfig(
        pairs=[list(pair) for pair in (pairs_cfg.pairs or [])],
        groups={},
        avoid_pairs=[],
        lookback_bars=max(int(pairs_cfg.lookback_bars), 50),
        entry_z=float(pairs_cfg.entry_z),
        exit_z=float(pairs_cfg.exit_z),
    )


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build_runtime_from_configs(
    config_dir: str | Path,
    active_symbols: list[str] | None = None,
    pairs_lookback_override: int | None = None,
    pairs_engine_factory: PairsEngineFactory | None = None,
    trend_engine_factory: TrendEngineFactory | None = None,
    regime_engine_factory: RegimeEngineFactory | None = None,
    runtime_overrides: dict[str, Any] | None = None,
) -> FxRuntimeEngine:
    """Build runtime engine from config files."""
    root = Path(config_dir)
    universe_cfg = load_universe_config(root / "universe.yaml")
    pairs_cfg = load_pairs_config(root / "pairs.yaml")
    runtime_cfg = load_runtime_config(root / "runtime.yaml")

    if runtime_overrides:
        for key, value in runtime_overrides.items():
            if not hasattr(runtime_cfg, key):
                raise ValueError(f"Unknown runtime override key: {key}")
            setattr(runtime_cfg, key, value)
        runtime_cfg.__post_init__()

    policy_path = root / "pairs_policy.yaml"
    overrides_path = root / "pairs_overrides.yaml"
    if policy_path.exists():
        pairs_policy_cfg = load_pairs_policy_with_overrides(
            policy_path,
            overrides_path if overrides_path.exists() else None,
        )
    else:
        pairs_policy_cfg = _default_pairs_policy_from_pairs_cfg(pairs_cfg)

    regime_path = root / "regime.yaml"
    regime_cfg = load_regime_config(regime_path) if regime_path.exists() else RegimeConfig()

    runtime = FxRuntimeEngine(
        universe_cfg=universe_cfg,
        pairs_cfg=pairs_cfg,
        runtime_cfg=runtime_cfg,
        pairs_policy_cfg=pairs_policy_cfg,
        regime_cfg=regime_cfg,
        active_symbols=active_symbols,
        pairs_lookback_override=pairs_lookback_override,
        pairs_engine_factory=pairs_engine_factory,
        trend_engine_factory=trend_engine_factory,
        regime_engine_factory=regime_engine_factory,
    )

    if runtime.runtime_cfg.live_persistence_enabled:
        config_files = {
            "universe": root / "universe.yaml",
            "pairs": root / "pairs.yaml",
            "runtime": root / "runtime.yaml",
            "pairs_policy": policy_path,
            "pairs_overrides": overrides_path,
            "regime": regime_path,
        }
        config_hashes = {
            name: _sha256(path)
            for name, path in config_files.items()
            if path.exists()
        }
        run_manifest = {
            "run_id": runtime.live_run_id,
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "git_sha": _safe_git_sha(root.parent),
            "runtime_mode": runtime.runtime_cfg.execution_mode,
            "data_source": runtime.runtime_cfg.data_source,
            "config_hashes": config_hashes,
            "config_files": {name: str(path) for name, path in config_files.items() if path.exists()},
        }
        config_snapshot = {
            "universe": asdict(universe_cfg),
            "pairs": asdict(pairs_cfg),
            "runtime": asdict(runtime_cfg),
            "pairs_policy": asdict(pairs_policy_cfg),
            "regime": asdict(regime_cfg),
        }
        runtime.set_live_metadata(run_manifest, config_snapshot, timestamp=datetime.now(tz=UTC))

    return runtime
