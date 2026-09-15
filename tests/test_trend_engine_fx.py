"""Trend engine tests."""

from __future__ import annotations

from fx_lean_engine.engines.trend import TrendEngine


def test_trend_engine_outputs_bounded_probabilities() -> None:
    engine = TrendEngine(symbols=["EURUSD"], lookback_bars=30)

    close = 1.0
    last_signal = None
    for _ in range(80):
        close *= 1.0008
        signals, _ = engine.update({"EURUSD": close})
        last_signal = signals[0]

    assert last_signal is not None
    assert 0.0 <= last_signal.p_up <= 1.0
    assert 0.0 <= last_signal.p_down <= 1.0
    assert 0.0 <= last_signal.confidence <= 1.0
    assert last_signal.direction in {"LONG", "SHORT", "FLAT"}
    assert last_signal.p_up > last_signal.p_down
