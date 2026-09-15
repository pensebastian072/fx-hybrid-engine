"""Consolidation/router tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_lean_engine.data.consolidation import BarRouter
from fx_lean_engine.types import Bar


def test_minute_to_15m_router_emits_exactly_one_bar() -> None:
    emitted: list[Bar] = []
    router = BarRouter(interval_minutes=15)
    router.register("EURUSD", emitted.append)

    start = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    for i in range(15):
        ts = start + timedelta(minutes=i)
        router.on_minute_bar(
            Bar(
                symbol="EURUSD",
                start=ts,
                end=ts + timedelta(minutes=1),
                open=1.10 + i * 0.0001,
                high=1.11 + i * 0.0001,
                low=1.09 + i * 0.0001,
                close=1.10 + i * 0.0002,
                volume=100.0,
            )
        )

    assert emitted == []

    ts = start + timedelta(minutes=15)
    router.on_minute_bar(
        Bar(
            symbol="EURUSD",
            start=ts,
            end=ts + timedelta(minutes=1),
            open=1.2,
            high=1.3,
            low=1.1,
            close=1.25,
            volume=100.0,
        )
    )

    assert len(emitted) == 1
    bar = emitted[0]
    assert bar.open > 1.0
    assert bar.close > 1.0
    assert bar.high >= bar.open
    assert bar.low <= bar.close
