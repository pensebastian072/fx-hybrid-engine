"""Phase 2 pairs engine gating tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_lean_engine.engines.pairs import PairsEngine


def test_phase2_pairs_engine_never_opens_non_tradable_pairs() -> None:
    engine = PairsEngine(
        pairs=[("EURUSD", "GBPUSD")],
        lookback_bars=30,
        entry_z=1.0,
        exit_z=0.3,
        max_holding_bars=120,
        notional_pct_nav=0.1,
    )

    start = datetime(2025, 1, 1, tzinfo=UTC)
    left = 1.10
    right = 1.30

    opened = []
    for i in range(200):
        left *= 1.00003
        right *= 0.9996 if 80 <= i < 120 else 1.00002
        _, intents = engine.update(
            {"EURUSD": left, "GBPUSD": right},
            start + timedelta(minutes=15 * i),
            pair_status_map={("EURUSD", "GBPUSD"): "WATCH"},
        )
        opened.extend([intent for intent in intents if intent.action == "open"])

    assert opened == []
