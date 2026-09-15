"""Unit tests for ops schema and append-audit validation."""
from __future__ import annotations

import pandas as pd

from fx_hybrid_engine.ops.schema import validate_ops_run_dir
from fx_hybrid_engine.ops.storage import (
    append_bars,
    append_broker_events,
    append_equity_curve,
    append_features,
    append_fills,
    append_orders,
    append_reconciliation_events,
    append_risk_events,
    append_signals,
    append_targets,
    initialize_run_metadata,
)


def _seed_valid_run(run_dir):
    run_id = "r1"
    initialize_run_metadata(
        run_dir,
        run_manifest={"run_id": run_id},
        config_snapshot={"ok": True},
    )
    base = pd.DataFrame(
        [{"timestamp": "2026-01-01T00:00:00+00:00", "symbol": "EURUSD", "run_id": run_id}]
    )
    append_bars(run_dir, base.assign(open=1.1, high=1.2, low=1.0, close=1.15), run_id=run_id)
    append_features(run_dir, base.assign(f1=0.1), run_id=run_id)
    append_signals(run_dir, base.assign(engine_source="trend"), run_id=run_id)
    append_targets(run_dir, base.assign(target_weight=0.1), run_id=run_id)
    append_orders(run_dir, base.assign(order_type="market"), run_id=run_id)
    append_fills(run_dir, base.assign(fill_price=1.16), run_id=run_id)
    append_equity_curve(run_dir, pd.DataFrame([{"timestamp": "2026-01-01T00:00:00+00:00", "run_id": run_id, "equity": 1.0}]), run_id=run_id)
    append_risk_events(run_dir, pd.DataFrame([{"timestamp": "2026-01-01T00:00:00+00:00", "run_id": run_id, "reason": "seed"}]), run_id=run_id)
    append_reconciliation_events(run_dir, [{"timestamp": "2026-01-01T00:00:00+00:00", "run_id": run_id, "reason": "seed", "resolved": True}], run_id=run_id)
    append_broker_events(run_dir, [{"event": "seed", "run_id": run_id, "timestamp": "2026-01-01T00:00:00+00:00"}], run_id=run_id)


def test_validate_ops_run_dir_passes(tmp_path):
    run_dir = tmp_path / "ops_run"
    _seed_valid_run(run_dir)
    ok, issues = validate_ops_run_dir(run_dir, require_run_id_columns=True, strict_append_audit=True)
    assert ok, "\n".join(i.message for i in issues)


def test_validate_ops_run_dir_fails_missing_file(tmp_path):
    run_dir = tmp_path / "ops_run"
    _seed_valid_run(run_dir)
    (run_dir / "fills.parquet").unlink()
    ok, issues = validate_ops_run_dir(run_dir, require_run_id_columns=True, strict_append_audit=True)
    assert not ok
    assert any("fills" in issue.message for issue in issues)
