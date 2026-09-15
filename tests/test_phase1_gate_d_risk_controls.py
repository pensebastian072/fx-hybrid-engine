"""Phase 1 Gate D tests: leverage cap, kill switch, and block_new_entries."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_lean_engine.backtest.synthetic import run_synthetic_backtest
from fx_lean_engine.orchestration.pipeline import build_runtime_from_configs
from fx_lean_engine.types import Bar, RegimeState, TradeIntent, TrendSignal


class _FlatPairsEngine:
    def __init__(self, pairs: list[tuple[str, str]]):
        self.pairs = list(pairs)

    def update(self, *_args, **_kwargs):
        return [], []


class _LongTrendEngine:
    def __init__(self, symbols: list[str]):
        self.symbols = list(symbols)

    def update(self, snapshot: dict[str, float]):
        symbol = sorted(snapshot.keys())[0]
        return (
            [TrendSignal(symbol=symbol, p_up=0.9, p_down=0.1, confidence=0.8, direction="LONG")],
            [
                TradeIntent(
                    engine="trend",
                    action="open",
                    symbol=symbol,
                    pair=None,
                    direction="LONG",
                    notional_pct_nav=0.10,
                    confidence=0.8,
                    reason="TEST_LONG",
                )
            ],
        )


class _StaticRegimeEngine:
    def update(self, *_args, **_kwargs) -> RegimeState:
        return RegimeState(
            state="TREND",
            p_trend=0.9,
            p_chop=0.1,
            p_risk_off=0.0,
            trend_weight=1.0,
            pairs_weight=0.0,
        )


def _pairs_factory(
    pair_tuples: list[tuple[str, str]],
    _lookback: int,
    _pairs_cfg,
    _runtime_cfg,
    _active_symbols: list[str],
) -> _FlatPairsEngine:
    return _FlatPairsEngine(pair_tuples)


def _trend_factory(active_symbols: list[str], _runtime_cfg) -> _LongTrendEngine:
    return _LongTrendEngine(active_symbols)


def _regime_factory(_active_symbols: list[str], _runtime_cfg) -> _StaticRegimeEngine:
    return _StaticRegimeEngine()


def _feed_runtime(runtime, bars: int = 48, start_index: int = 0) -> None:
    start = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    close = 1.0
    for i in range(start_index, start_index + bars):
        close *= 1.0004
        ts = start + timedelta(minutes=15 * i)
        runtime.on_consolidated_bar(
            Bar(
                symbol="EURUSD",
                start=ts,
                end=ts + timedelta(minutes=15),
                open=close * 0.999,
                high=close * 1.001,
                low=close * 0.998,
                close=close,
                volume=1000.0,
            )
        )


def test_phase1_gate_d_block_new_entries_prevents_opens(tmp_path: Path) -> None:
    config_dir = Path(__file__).resolve().parents[1] / "configs"
    runtime = build_runtime_from_configs(
        config_dir=config_dir,
        active_symbols=["EURUSD"],
        pairs_lookback_override=30,
        pairs_engine_factory=_pairs_factory,
        trend_engine_factory=_trend_factory,
        regime_engine_factory=_regime_factory,
    )
    runtime.runtime_cfg.block_new_entries = True

    _feed_runtime(runtime, bars=52)

    approved_open = [
        row
        for row in runtime.artifacts.orders
        if str(row.get("status")) == "approved" and str(row.get("action")) == "open"
    ]
    assert approved_open == []
    assert any(str(row.get("reason")) == "BLOCK_NEW_ENTRIES" for row in runtime.artifacts.risk_events)


def test_phase1_gate_d_kill_switch_forces_close() -> None:
    config_dir = Path(__file__).resolve().parents[1] / "configs"
    runtime = build_runtime_from_configs(
        config_dir=config_dir,
        active_symbols=["EURUSD"],
        pairs_lookback_override=30,
        pairs_engine_factory=_pairs_factory,
        trend_engine_factory=_trend_factory,
        regime_engine_factory=_regime_factory,
    )
    runtime.runtime_cfg.kill_switch_enabled = False

    _feed_runtime(runtime, bars=52, start_index=0)
    approved_open_before = [
        row
        for row in runtime.artifacts.orders
        if str(row.get("status")) == "approved" and str(row.get("action")) == "open"
    ]
    assert approved_open_before

    runtime.runtime_cfg.kill_switch_enabled = True
    _feed_runtime(runtime, bars=5, start_index=52)

    forced_closes = [
        row
        for row in runtime.artifacts.orders
        if str(row.get("status")) == "approved" and str(row.get("reason")) == "KILL_SWITCH_FORCE_EXIT"
    ]
    assert forced_closes
    assert any(str(row.get("event_type")) == "KILL_SWITCH" for row in runtime.artifacts.risk_events)


def test_phase1_gate_d_leverage_cap_not_breached(tmp_path: Path) -> None:
    out_dir = run_synthetic_backtest(tmp_path / "phase1_gate_d")
    metrics_path = out_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert float(metrics["max_gross_exposure"]) <= 2.0 + 1e-12
