from __future__ import annotations

from fx_hybrid_engine.lean.qc_state_store import load_state, save_state
from fx_hybrid_engine.lean.runtime_safety import evaluate_runtime_safety
from fx_hybrid_engine.ops.circuit_breakers import BreakerContext
from fx_hybrid_engine.ops.health import HealthPolicy
from fx_hybrid_engine.utils.config import CircuitBreakersConfig, ReconciliationConfig


def test_qc_state_store_local_fallback_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = {"close_only": True, "ladder_stage": "stage1_micro"}
    save_state(namespace="fxhe/test", payload=payload, owner=None)
    loaded = load_state(namespace="fxhe/test", owner=None)
    assert loaded["close_only"] is True
    assert loaded["ladder_stage"] == "stage1_micro"


def test_runtime_safety_stale_data_sets_close_only():
    snap = evaluate_runtime_safety(
        run_id="r1",
        last_bar_timestamp_utc="2026-01-01T00:00:00+00:00",
        consecutive_rejects=0,
        missing_bars=2,
        broker_connected=True,
        health_policy=HealthPolicy(data_stale_seconds=1, degraded_rejects=2, broker_down_rejects=3, max_missing_bars=1),
        breaker_ctx=BreakerContext(
            daily_return=0.0,
            weekly_return=0.0,
            consecutive_losses=0,
            realized_vol_multiple=1.0,
            reject_count=0,
        ),
        circuit_breakers_cfg=CircuitBreakersConfig(),
        reconciliation_cfg=ReconciliationConfig(enabled=False),
    )
    assert snap.close_only is True
    assert snap.health_state in {"DATA_STALE", "DEGRADED"}


def test_runtime_safety_reject_spike_and_reconcile_trigger():
    snap = evaluate_runtime_safety(
        run_id="r1",
        last_bar_timestamp_utc="2026-01-01T00:00:00+00:00",
        consecutive_rejects=10,
        missing_bars=0,
        broker_connected=True,
        health_policy=HealthPolicy(data_stale_seconds=300, degraded_rejects=2, broker_down_rejects=8, max_missing_bars=1),
        breaker_ctx=BreakerContext(
            daily_return=0.0,
            weekly_return=0.0,
            consecutive_losses=0,
            realized_vol_multiple=1.0,
            reject_count=10,
        ),
        circuit_breakers_cfg=CircuitBreakersConfig(),
        reconciliation_cfg=ReconciliationConfig(enabled=True),
        expected_holdings={"EURUSD": 1.0},
        actual_holdings={"EURUSD": 0.5},
        expected_order_ids={"o1"},
        actual_order_ids={"o2"},
        mismatch_cycles=3,
    )
    assert snap.close_only is True
    assert snap.reconciliation is not None
    assert snap.reconciliation.pause_entries is True
