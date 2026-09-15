"""Generalized circuit-breaker evaluation and risk-event generation."""
from __future__ import annotations

from dataclasses import dataclass

from fx_hybrid_engine.utils.config import CircuitBreakersConfig


@dataclass(slots=True)
class BreakerContext:
    daily_return: float
    weekly_return: float
    consecutive_losses: int
    realized_vol_multiple: float
    reject_count: int


def evaluate_circuit_breakers(
    ctx: BreakerContext,
    cfg: CircuitBreakersConfig,
) -> dict[str, object]:
    triggered: list[str] = []
    reduce_exposure_multiplier = 1.0
    pause_entries = False

    if ctx.daily_return <= -abs(cfg.daily_loss_limit):
        triggered.append("daily_loss_limit")
        pause_entries = True
    if ctx.weekly_return <= -abs(cfg.weekly_loss_limit):
        triggered.append("weekly_loss_limit")
        pause_entries = True
    if int(ctx.consecutive_losses) >= int(cfg.max_consecutive_losses):
        triggered.append("max_consecutive_losses")
        pause_entries = True
    if ctx.realized_vol_multiple >= float(cfg.vol_spike_threshold):
        triggered.append("volatility_spike")
        reduce_exposure_multiplier = min(reduce_exposure_multiplier, 0.5)
    if int(ctx.reject_count) >= int(cfg.reject_spike_threshold):
        triggered.append("reject_spike")
        pause_entries = True

    return {
        "triggered": triggered,
        "pause_entries": pause_entries,
        "reduce_exposure_multiplier": reduce_exposure_multiplier,
        "symbol_cooldown_minutes": int(cfg.symbol_cooldown_minutes) if triggered else 0,
    }


def breaker_risk_events(
    run_id: str,
    timestamp: str,
    result: dict[str, object],
) -> list[dict[str, object]]:
    events = []
    for reason in result.get("triggered", []):
        events.append(
            {
                "timestamp": timestamp,
                "run_id": run_id,
                "reason": str(reason),
                "pause_entries": bool(result.get("pause_entries", False)),
                "reduce_exposure_multiplier": float(result.get("reduce_exposure_multiplier", 1.0)),
            }
        )
    return events

