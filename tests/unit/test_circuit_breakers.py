"""Unit tests for circuit breaker triggers and risk-event generation."""
from __future__ import annotations

from fx_hybrid_engine.ops.circuit_breakers import (
    BreakerContext,
    breaker_risk_events,
    evaluate_circuit_breakers,
)
from fx_hybrid_engine.utils.config import CircuitBreakersConfig


def test_daily_loss_breaker_triggers_pause():
    cfg = CircuitBreakersConfig(daily_loss_limit=0.03, weekly_loss_limit=0.06, max_consecutive_losses=5)
    result = evaluate_circuit_breakers(
        BreakerContext(
            daily_return=-0.04,
            weekly_return=0.0,
            consecutive_losses=0,
            realized_vol_multiple=1.0,
            reject_count=0,
        ),
        cfg,
    )
    assert "daily_loss_limit" in result["triggered"]
    assert result["pause_entries"] is True


def test_vol_spike_reduces_exposure_without_pause():
    cfg = CircuitBreakersConfig(vol_spike_threshold=2.0, reject_spike_threshold=9)
    result = evaluate_circuit_breakers(
        BreakerContext(
            daily_return=0.0,
            weekly_return=0.0,
            consecutive_losses=0,
            realized_vol_multiple=2.5,
            reject_count=0,
        ),
        cfg,
    )
    assert "volatility_spike" in result["triggered"]
    assert result["pause_entries"] is False
    assert result["reduce_exposure_multiplier"] < 1.0


def test_breaker_event_rows_generated():
    result = {"triggered": ["daily_loss_limit", "reject_spike"], "pause_entries": True, "reduce_exposure_multiplier": 0.5}
    rows = breaker_risk_events("run1", "2026-01-01T00:00:00+00:00", result)
    assert len(rows) == 2
    assert {r["reason"] for r in rows} == {"daily_loss_limit", "reject_spike"}

