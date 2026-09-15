"""Pairs engine tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_lean_engine.engines.pairs import PairsEngine


def test_pairs_engine_emits_entry_and_exit() -> None:
    engine = PairsEngine(
        pairs=[("EURUSD", "GBPUSD")],
        lookback_bars=30,
        entry_z=1.0,
        exit_z=0.3,
        max_holding_bars=50,
        notional_pct_nav=0.1,
    )

    intents = []
    start = datetime(2025, 1, 1, tzinfo=UTC)
    left = 1.10
    right = 1.30

    for i in range(180):
        left *= 1.00005
        if 80 <= i < 95:
            right *= 0.9980
        elif 95 <= i < 120:
            right *= 1.0015
        else:
            right *= 1.00002

        _, new_intents = engine.update(
            {"EURUSD": left, "GBPUSD": right},
            start + timedelta(minutes=15 * i),
        )
        intents.extend(new_intents)

    reasons = [intent.reason for intent in intents]
    assert "PAIR_ENTRY_Z" in reasons
    assert any(reason in {"PAIR_EXIT_Z", "PAIR_MAX_HOLD"} for reason in reasons)
