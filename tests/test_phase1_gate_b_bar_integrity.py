"""Phase 1 Gate B tests: bar ordering and gap handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_lean_engine.data.health import BarHealthChecker


def test_phase1_gate_b_bar_ordering_duplicate_and_gap() -> None:
    checker = BarHealthChecker(
        bar_interval_minutes=15,
        gap_warn_threshold_minutes=30,
        strict_bar_ordering=True,
    )

    t0 = datetime(2025, 1, 1, 0, 15, tzinfo=UTC)
    ok, events = checker.check("EURUSD", t0)
    assert ok is True
    assert events == []

    ok, events = checker.check("EURUSD", t0 + timedelta(minutes=15))
    assert ok is True
    assert events == []

    ok, events = checker.check("EURUSD", t0 + timedelta(minutes=15))
    assert ok is False
    assert any(event.event_type == "DUPLICATE_TIMESTAMP" for event in events)

    ok, events = checker.check("EURUSD", t0 + timedelta(minutes=75))
    assert ok is True
    assert any(event.event_type == "MISSING_BAR_GAP" for event in events)


def test_phase1_gate_b_non_strict_mode_warns_without_dropping() -> None:
    checker = BarHealthChecker(
        bar_interval_minutes=15,
        gap_warn_threshold_minutes=30,
        strict_bar_ordering=False,
    )

    t0 = datetime(2025, 1, 1, 0, 15, tzinfo=UTC)
    checker.check("GBPUSD", t0)
    ok, events = checker.check("GBPUSD", t0)
    assert ok is True
    assert any(event.event_type == "DUPLICATE_TIMESTAMP" for event in events)
