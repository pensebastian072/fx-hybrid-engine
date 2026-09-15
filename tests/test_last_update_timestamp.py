"""Tests for last_update_timestamp tracking in FxRuntimeEngine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_lean_engine.orchestration.pipeline import build_runtime_from_configs
from fx_lean_engine.types import Bar, RegimeState


class _StubPairs:
    def __init__(self, pairs, *_, **__):
        self.pairs = list(pairs)

    def update(self, *_, **__):
        return [], []


class _StubTrend:
    def __init__(self, symbols, *_, **__):
        self.symbols = list(symbols)

    def update(self, *_, **__):
        return [], []


class _StubRegime:
    def update(self, *_, **__):
        return RegimeState(
            state="CHOP",
            p_trend=0.2,
            p_chop=0.8,
            p_risk_off=0.0,
            trend_weight=0.0,
            pairs_weight=0.0,
        )


def _build_runtime():
    config_dir = Path(__file__).resolve().parents[1] / "configs"
    return build_runtime_from_configs(
        config_dir=config_dir,
        active_symbols=["EURUSD"],
        pairs_lookback_override=30,
        pairs_engine_factory=lambda pairs, *a, **kw: _StubPairs(pairs),
        trend_engine_factory=lambda symbols, *a, **kw: _StubTrend(symbols),
        regime_engine_factory=lambda *a, **kw: _StubRegime(),
    )


def test_last_update_timestamp_none_before_any_bar() -> None:
    runtime = _build_runtime()
    assert runtime.last_update_timestamp is None


def test_last_update_timestamp_set_after_bar() -> None:
    runtime = _build_runtime()
    ts = datetime(2025, 6, 1, 10, 0, tzinfo=UTC)
    runtime.on_consolidated_bar(
        Bar(
            symbol="EURUSD",
            start=ts,
            end=ts + timedelta(minutes=15),
            open=1.1000,
            high=1.1010,
            low=1.0990,
            close=1.1005,
            volume=1000.0,
        )
    )
    assert runtime.last_update_timestamp == ts + timedelta(minutes=15)


def test_last_update_timestamp_advances_with_bars() -> None:
    runtime = _build_runtime()
    start = datetime(2025, 6, 1, 10, 0, tzinfo=UTC)
    for i in range(5):
        bar_end = start + timedelta(minutes=15 * (i + 1))
        runtime.on_consolidated_bar(
            Bar(
                symbol="EURUSD",
                start=start + timedelta(minutes=15 * i),
                end=bar_end,
                open=1.1000,
                high=1.1010,
                low=1.0990,
                close=1.1005,
                volume=1000.0,
            )
        )
    expected_last = start + timedelta(minutes=15 * 5)
    assert runtime.last_update_timestamp == expected_last


def test_last_update_at_in_build_metrics() -> None:
    runtime = _build_runtime()
    ts = datetime(2025, 6, 1, 10, 0, tzinfo=UTC)
    runtime.on_consolidated_bar(
        Bar(
            symbol="EURUSD",
            start=ts,
            end=ts + timedelta(minutes=15),
            open=1.1000,
            high=1.1010,
            low=1.0990,
            close=1.1005,
            volume=1000.0,
        )
    )
    metrics = runtime.build_metrics(run_id="test", start="2025-06-01", end="2025-06-01", resolution="15m")
    assert "last_update_at" in metrics
    assert metrics["last_update_at"] == (ts + timedelta(minutes=15)).isoformat()


def test_last_update_at_none_in_metrics_when_no_bar() -> None:
    runtime = _build_runtime()
    metrics = runtime.build_metrics(run_id="test", start="2025-06-01", end="2025-06-01", resolution="15m")
    assert metrics.get("last_update_at") is None
