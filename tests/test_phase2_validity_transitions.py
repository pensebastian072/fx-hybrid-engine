"""Phase 2 validity transition tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_lean_engine.config.models import PairsPolicyConfig
from fx_lean_engine.pairs.validity import PairValidityManager
from fx_lean_engine.types import PairFitResult, PairStatus


def _fit(ts: datetime, p_value: float, beta_drift: float = 0.0, spread_std: float = 0.01) -> PairFitResult:
    return PairFitResult(
        pair=("EURUSD", "GBPUSD"),
        beta=1.0,
        intercept=0.0,
        p_value=float(p_value),
        spread_std=float(spread_std),
        half_life=12.0,
        beta_drift=float(beta_drift),
        spread_last_z=0.1,
        timestamp=ts,
    )


def test_phase2_validity_transitions_tradable_watch_disabled_recover() -> None:
    policy = PairsPolicyConfig(
        pairs=[["EURUSD", "GBPUSD"]],
        groups={},
        avoid_pairs=[],
        lookback_bars=200,
        p_enter=0.05,
        p_exit=0.15,
        p_break=0.25,
        p_recover=0.05,
        break_scans_required=2,
        recover_scans_required=2,
        disable_cooldown_bars=1,
    )
    manager = PairValidityManager(policy=policy, bar_interval_minutes=15)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)

    manager.apply_scan([_fit(t0, p_value=0.01)])
    assert manager.get_status_map()[("EURUSD", "GBPUSD")] == str(PairStatus.TRADABLE)

    manager.apply_scan([_fit(t0 + timedelta(minutes=15), p_value=0.20)])
    assert manager.get_status_map()[("EURUSD", "GBPUSD")] == str(PairStatus.WATCH)

    manager.apply_scan([_fit(t0 + timedelta(minutes=30), p_value=0.30)])
    manager.apply_scan([_fit(t0 + timedelta(minutes=45), p_value=0.30)])
    assert manager.get_status_map()[("EURUSD", "GBPUSD")] == str(PairStatus.DISABLED)

    manager.apply_scan([_fit(t0 + timedelta(minutes=61), p_value=0.01)])
    assert manager.get_status_map()[("EURUSD", "GBPUSD")] == str(PairStatus.DISABLED)

    manager.apply_scan([_fit(t0 + timedelta(minutes=76), p_value=0.01)])
    assert manager.get_status_map()[("EURUSD", "GBPUSD")] == str(PairStatus.TRADABLE)
