"""Unit tests for Phase 6 ops storage, health, and reconciliation contracts."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from fx_hybrid_engine.ops.health import BROKER_DOWN, DATA_STALE, HealthPolicy, evaluate_health
from fx_hybrid_engine.ops.reconcile import evaluate_reconciliation
from fx_hybrid_engine.ops.storage import (
    append_broker_events,
    append_signals,
    initialize_run_metadata,
)


def test_append_only_parquet_contract(tmp_path):
    run_dir = tmp_path / "ops_run"
    first = pd.DataFrame(
        [
            {"timestamp": "2026-01-01T00:00:00+00:00", "symbol": "EURUSD", "score": 0.1, "run_id": "r1"},
            {"timestamp": "2026-01-01T00:01:00+00:00", "symbol": "GBPUSD", "score": 0.2, "run_id": "r1"},
        ]
    )
    second = pd.DataFrame(
        [
            {"timestamp": "2026-01-01T00:02:00+00:00", "symbol": "EURUSD", "score": 0.3, "run_id": "r1"},
        ]
    )
    path = append_signals(run_dir, first)
    append_signals(run_dir, second)
    out = pd.read_parquet(path)
    assert len(out) == 3
    assert list(out["symbol"]) == ["EURUSD", "GBPUSD", "EURUSD"]
    assert set(out["run_id"].unique()) == {"r1"}
    audit_path = run_dir / "write_audit.jsonl"
    assert audit_path.exists()
    assert len([ln for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]) >= 2


def test_append_broker_events_jsonl(tmp_path):
    run_dir = tmp_path / "ops_run"
    path = append_broker_events(
        run_dir,
        [
            {"ts": "2026-01-01T00:00:00+00:00", "event": "order_submitted"},
            {"ts": "2026-01-01T00:00:01+00:00", "event": "order_filled"},
        ],
    )
    append_broker_events(
        run_dir,
        [{"ts": "2026-01-01T00:00:02+00:00", "event": "heartbeat"}],
    )
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    payload = json.loads(lines[0])
    assert payload["event"] == "order_submitted"


def test_initialize_run_metadata_is_write_once(tmp_path):
    run_dir = tmp_path / "ops_run"
    initialize_run_metadata(
        run_dir,
        run_manifest={"run_id": "r1", "created_at_utc": "2026-01-01T00:00:00+00:00"},
        config_snapshot={"risk": {"max_leverage": 2.0}},
    )
    with pytest.raises(FileExistsError):
        initialize_run_metadata(
            run_dir,
            run_manifest={"run_id": "r1"},
            config_snapshot={"risk": {"max_leverage": 2.0}},
        )


def test_health_close_only_triggered_on_stale_or_rejects():
    policy = HealthPolicy(data_stale_seconds=60, degraded_rejects=2, broker_down_rejects=3)
    stale = evaluate_health(
        now_utc="2026-01-01T00:02:00+00:00",
        last_bar_timestamp_utc="2026-01-01T00:00:00+00:00",
        consecutive_rejects=0,
        policy=policy,
    )
    rejects = evaluate_health(
        now_utc="2026-01-01T00:00:10+00:00",
        last_bar_timestamp_utc="2026-01-01T00:00:00+00:00",
        consecutive_rejects=3,
        policy=policy,
    )
    assert stale["close_only"] is True
    assert rejects["close_only"] is True
    assert stale["state"] == DATA_STALE
    assert rejects["state"] == BROKER_DOWN


def test_reconciliation_detects_position_and_order_mismatch():
    result = evaluate_reconciliation(
        expected_holdings={"EURUSD": 1000.0, "GBPUSD": -500.0},
        actual_holdings={"EURUSD": 900.0, "USDJPY": 20.0},
        expected_order_ids={"o1", "o2"},
        actual_order_ids={"o2", "o3"},
    )
    assert result.pause_entries is True
    assert result.attempt_reconcile is True
    assert result.flatten_required is False
    assert result.holdings_match is False
    assert result.orders_match is False
    assert result.missing_symbols == ["GBPUSD"]
    assert result.extra_symbols == ["USDJPY"]
    assert result.missing_order_ids == ["o1"]
    assert result.extra_order_ids == ["o3"]
