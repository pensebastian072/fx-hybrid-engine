"""Phase 2 breakdown disable tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_lean_engine.config.models import PairsPolicyConfig
from fx_lean_engine.engines.pairs import PairsEngine
from fx_lean_engine.pairs.validity import PairValidityManager
from fx_lean_engine.types import PairFitResult, PairStatus


def _fit(ts: datetime, p_value: float, beta_drift: float = 0.0, spread_std: float = 0.01) -> PairFitResult:
    return PairFitResult(
        pair=("EURUSD", "GBPUSD"),
        beta=1.0,
        intercept=0.0,
        p_value=p_value,
        spread_std=spread_std,
        half_life=10.0,
        beta_drift=beta_drift,
        spread_last_z=0.2,
        timestamp=ts,
    )


def test_phase2_breakdown_disables_pair_and_blocks_entries() -> None:
    policy = PairsPolicyConfig(
        pairs=[["EURUSD", "GBPUSD"]],
        groups={},
        avoid_pairs=[],
        break_scans_required=2,
        disable_cooldown_bars=4,
    )
    manager = PairValidityManager(policy=policy, bar_interval_minutes=15)

    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    manager.apply_scan([_fit(t0, p_value=0.01)])
    rows, events = manager.apply_scan([_fit(t0 + timedelta(minutes=15), p_value=0.3, beta_drift=0.3)])
    assert rows
    rows, events = manager.apply_scan([_fit(t0 + timedelta(minutes=30), p_value=0.35, beta_drift=0.35)])
    assert any(event.get("to") == str(PairStatus.DISABLED) for event in events)

    status_map = manager.get_status_map()
    assert status_map[("EURUSD", "GBPUSD")] == str(PairStatus.DISABLED)

    engine = PairsEngine(
        pairs=[("EURUSD", "GBPUSD")],
        lookback_bars=30,
        entry_z=1.0,
        exit_z=0.3,
        max_holding_bars=120,
        notional_pct_nav=0.1,
    )

    left = 1.10
    right = 1.30
    opened = []
    for i in range(160):
        left *= 1.00004
        right *= 0.9995 if i > 60 else 1.00003
        _, intents = engine.update(
            {"EURUSD": left, "GBPUSD": right},
            t0 + timedelta(minutes=15 * i),
            pair_status_map=status_map,
        )
        opened.extend([intent for intent in intents if intent.action == "open"])

    assert opened == []
