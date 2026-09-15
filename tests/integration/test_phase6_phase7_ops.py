"""Integration tests for Phase 6 precheck and Phase 7 weekly-eval scaffolding."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from fx_hybrid_engine.evaluation.weekly_eval import run_weekly_evaluation
from fx_hybrid_engine.ops.precheck import run_phase6_precheck
from fx_hybrid_engine.ops.promote_check import run_promotion_check
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
from fx_hybrid_engine.utils.config import load_config

pytestmark = pytest.mark.integration


def _seed_run(run_dir: Path, run_id: str = "itest_ops") -> None:
    initialize_run_metadata(run_dir, {"run_id": run_id}, {"ok": True})
    base = pd.DataFrame([{"timestamp": "2026-01-01T00:00:00+00:00", "symbol": "EURUSD", "run_id": run_id}])
    append_bars(run_dir, base.assign(open=1.0, high=1.1, low=0.9, close=1.05), run_id=run_id)
    append_features(run_dir, base.assign(f=0.1), run_id=run_id)
    append_signals(run_dir, base.assign(engine_source="trend"), run_id=run_id)
    append_targets(run_dir, base.assign(target_weight=0.1), run_id=run_id)
    append_orders(run_dir, base.assign(order_type="market"), run_id=run_id)
    append_fills(run_dir, base.assign(fill_price=1.06), run_id=run_id)
    append_equity_curve(run_dir, pd.DataFrame([{"timestamp": "2026-01-01T00:00:00+00:00", "run_id": run_id, "equity": 1.0}]), run_id=run_id)
    append_risk_events(run_dir, pd.DataFrame([{"timestamp": "2026-01-01T00:00:00+00:00", "run_id": run_id, "reason": "ok"}]), run_id=run_id)
    append_reconciliation_events(run_dir, [{"timestamp": "2026-01-01T00:00:00+00:00", "run_id": run_id, "reason": "ok", "resolved": True}], run_id=run_id)
    append_broker_events(run_dir, [{"timestamp": "2026-01-01T00:00:00+00:00", "run_id": run_id, "event": "ok"}], run_id=run_id)
    (run_dir / "paper_safety_summary.json").write_text(
        json.dumps(
            {
                "health_state": "DATA_OK",
                "close_only": False,
                "health_reasons": [],
                "breaker_result": {"triggered": [], "pause_entries": False},
                "expected_holdings_sign": {},
                "actual_holdings_sign": {},
                "broker_positions_available": False,
                "broker_orders_available": False,
                "reconciliation_enabled": False,
                "reconciliation_mode": "skipped",
                "reconciliation_status": "skipped",
                "reconciliation_reason": "broker_state_unavailable_or_local_only",
                "missing_bars_count": 0,
                "latest_bar_timestamp": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )


def test_phase6_precheck_pass_and_fail(tmp_path):
    run_dir = tmp_path / "ops_run"
    _seed_run(run_dir)
    report_json, report_md, ok = run_phase6_precheck(run_dir, strict_full=True)
    assert ok
    assert report_json.exists()
    assert report_md.exists()

    (run_dir / "signals.parquet").unlink()
    _, _, ok2 = run_phase6_precheck(run_dir, strict_full=True)
    assert not ok2


def test_phase6_precheck_accepts_explicit_local_paper_reconciliation_skip(tmp_path):
    run_dir = tmp_path / "ops_local_paper"
    _seed_run(run_dir, run_id="itest_local_paper")
    (run_dir / "paper_safety_summary.json").write_text(
        json.dumps(
            {
                "health_state": "DATA_OK",
                "close_only": False,
                "health_reasons": [],
                "breaker_result": {"triggered": [], "pause_entries": False},
                "expected_holdings_sign": {},
                "actual_holdings_sign": {},
                "broker_positions_available": False,
                "broker_orders_available": False,
                "reconciliation_enabled": False,
                "reconciliation_mode": "skipped",
                "reconciliation_status": "skipped",
                "reconciliation_reason": "broker_state_unavailable_or_local_only",
                "missing_bars_count": 0,
                "latest_bar_timestamp": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    report_json, _, ok = run_phase6_precheck(run_dir, strict_full=True, rail="local_paper")
    assert ok
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    gate = next(g for g in payload["gates"] if g["name"] == "reconciliation_mode_explicit")
    assert gate["passed"] is True
    assert gate["details"]["mode"] == "skipped"


def test_phase6_precheck_accepts_legacy_skipped_reconciliation_event(tmp_path):
    run_dir = tmp_path / "ops_local_paper_legacy"
    _seed_run(run_dir, run_id="itest_local_paper_legacy")
    (run_dir / "paper_safety_summary.json").unlink()
    # Legacy artifacts may only include event names without explicit mode/status keys.
    append_reconciliation_events(
        run_dir,
        [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "run_id": "itest_local_paper_legacy",
                "event": "paper_reconciliation_skipped",
                "reason": "broker_state_unavailable_or_local_only",
                "resolved": True,
            }
        ],
        run_id="itest_local_paper_legacy",
    )

    report_json, _, ok = run_phase6_precheck(run_dir, strict_full=True, rail="local_paper")
    assert ok
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    gate = next(g for g in payload["gates"] if g["name"] == "reconciliation_mode_explicit")
    assert gate["passed"] is True
    assert gate["details"]["mode"] == "skipped"
    assert gate["details"]["source"] == "reconciliation_events.jsonl"


def test_phase6_precheck_falls_back_from_legacy_safety_to_events(tmp_path):
    run_dir = tmp_path / "ops_local_paper_legacy_safety"
    _seed_run(run_dir, run_id="itest_local_paper_legacy_safety")
    (run_dir / "paper_safety_summary.json").write_text(
        json.dumps(
            {
                "health_state": "DATA_OK",
                "close_only": False,
                "reconciliation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    append_reconciliation_events(
        run_dir,
        [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "run_id": "itest_local_paper_legacy_safety",
                "event": "paper_reconciliation_skipped",
                "reason": "broker_state_unavailable_or_local_only",
                "resolved": True,
            }
        ],
        run_id="itest_local_paper_legacy_safety",
    )

    report_json, _, ok = run_phase6_precheck(run_dir, strict_full=True, rail="local_paper")
    assert ok
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    gate = next(g for g in payload["gates"] if g["name"] == "reconciliation_mode_explicit")
    assert gate["passed"] is True
    assert gate["details"]["mode"] == "skipped"
    assert gate["details"]["source"] == "reconciliation_events.jsonl"


def test_weekly_eval_smoke(tmp_path):
    cfg_raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    cfg_raw["walkforward"]["output_root"] = str(tmp_path / "wf")
    cfg_raw["walkforward"]["data_profile"] = "local_smoke"
    cfg_raw["walkforward"]["auto_report"] = True
    cfg_raw["walkforward"]["start_date"] = "2021-01-01"
    cfg_raw["walkforward"]["end_date"] = "2022-01-01"
    cfg_raw["walkforward"]["train_window_days"] = 120
    cfg_raw["walkforward"]["test_window_days"] = 30
    cfg_raw["walkforward"]["step_days"] = 30
    cfg_raw["weekly_evaluation"]["max_splits"] = 1
    cfg_raw["weekly_evaluation"]["run_robustness"] = False
    cfg_raw["robustness"]["param_sweep_samples"] = 0
    cfg_raw["trend_engine"]["sma_fast"] = 20
    cfg_raw["trend_engine"]["sma_slow"] = 60
    cfg_path = tmp_path / "weekly.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg_raw, sort_keys=False), encoding="utf-8")

    run_dir, decision_path = run_weekly_evaluation(config_path=cfg_path, run_id="itest_weekly")
    assert run_dir.exists()
    assert decision_path.exists()
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    assert {"action", "current_stage", "next_stage"} <= set(payload["ladder"].keys())


def test_promote_check_smoke(tmp_path):
    cfg_raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    cfg_path = tmp_path / "promote.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg_raw, sort_keys=False), encoding="utf-8")
    cfg = load_config(cfg_path)

    wf_run = tmp_path / "wf"
    wf_run.mkdir(parents=True, exist_ok=True)
    (wf_run / "phase5_report_summary.json").write_text(
        json.dumps(
            {
                "final_go": True,
                "go_no_go": {
                    "costs_do_not_kill_edge": True,
                    "worst_split_drawdown_survivable": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (wf_run / "proof_checks.json").write_text(json.dumps({"pass": True}), encoding="utf-8")

    paper_run = tmp_path / "paper"
    _seed_run(paper_run, run_id="itest_promote")
    decision, out_path = run_promotion_check(cfg=cfg, wf_run_dir=wf_run, paper_run_dir=paper_run)
    assert out_path.exists()
    assert "ladder" in decision and "action" in decision["ladder"]
