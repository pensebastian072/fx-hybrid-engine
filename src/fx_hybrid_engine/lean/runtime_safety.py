"""Runtime safety orchestration helpers for QC paper/live loops."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fx_hybrid_engine.ops.circuit_breakers import (
    BreakerContext,
    breaker_risk_events,
    evaluate_circuit_breakers,
)
from fx_hybrid_engine.ops.health import HealthPolicy, evaluate_health
from fx_hybrid_engine.ops.reconcile import ReconcileResult, evaluate_reconciliation
from fx_hybrid_engine.utils.config import CircuitBreakersConfig, ReconciliationConfig


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class RuntimeSafetySnapshot:
    now_utc: str
    health_state: str
    close_only: bool
    health_reasons: list[str]
    breaker_result: dict[str, object]
    reconciliation: ReconcileResult | None
    risk_events: list[dict[str, object]]


def evaluate_runtime_safety(
    *,
    run_id: str,
    last_bar_timestamp_utc: object | None,
    consecutive_rejects: int,
    missing_bars: int,
    broker_connected: bool,
    health_policy: HealthPolicy,
    breaker_ctx: BreakerContext,
    circuit_breakers_cfg: CircuitBreakersConfig,
    reconciliation_cfg: ReconciliationConfig | None = None,
    expected_holdings: dict[str, float] | None = None,
    actual_holdings: dict[str, float] | None = None,
    expected_order_ids: set[str] | None = None,
    actual_order_ids: set[str] | None = None,
    mismatch_cycles: int = 0,
) -> RuntimeSafetySnapshot:
    now = _utc_now()
    health = evaluate_health(
        now_utc=now,
        last_bar_timestamp_utc=last_bar_timestamp_utc,
        consecutive_rejects=consecutive_rejects,
        policy=health_policy,
        missing_bars=missing_bars,
        broker_connected=broker_connected,
    )
    breaker = evaluate_circuit_breakers(breaker_ctx, circuit_breakers_cfg)
    close_only = bool(health["close_only"]) or bool(breaker["pause_entries"])
    risk_events = breaker_risk_events(run_id, now.isoformat(), breaker)
    if bool(health["close_only"]):
        risk_events.append(
            {
                "timestamp": now.isoformat(),
                "run_id": run_id,
                "reason": "close_only_health_guard",
                "state": health["state"],
                "health_reasons": health.get("reasons", []),
            }
        )

    rec_result: ReconcileResult | None = None
    if reconciliation_cfg and reconciliation_cfg.enabled:
        rec_result = evaluate_reconciliation(
            expected_holdings=expected_holdings or {},
            actual_holdings=actual_holdings or {},
            expected_order_ids=expected_order_ids or set(),
            actual_order_ids=actual_order_ids or set(),
            tolerance=reconciliation_cfg.qty_tolerance,
            mismatch_cycles=mismatch_cycles,
            persistent_mismatch_cycles=reconciliation_cfg.persistent_mismatch_cycles,
            auto_flatten_on_persistent_mismatch=reconciliation_cfg.auto_flatten_on_persistent_mismatch,
        )
        if rec_result.pause_entries:
            close_only = True
            risk_events.append(
                {
                    "timestamp": now.isoformat(),
                    "run_id": run_id,
                    "reason": "close_only_reconciliation_guard",
                    "pause_entries": rec_result.pause_entries,
                    "flatten_required": rec_result.flatten_required,
                }
            )

    return RuntimeSafetySnapshot(
        now_utc=now.isoformat(),
        health_state=str(health["state"]),
        close_only=close_only,
        health_reasons=[str(r) for r in health.get("reasons", [])],
        breaker_result=breaker,
        reconciliation=rec_result,
        risk_events=risk_events,
    )
