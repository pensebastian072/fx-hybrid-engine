"""Unit tests for micro-live ladder and model registry scaffolding."""
from __future__ import annotations

from fx_hybrid_engine.ops.ladder import decide_ladder_action, normalize_stage, resolve_ladder_caps
from fx_hybrid_engine.ops.model_registry import refresh_due, register_model_version
from fx_hybrid_engine.utils.config import ModelRegistryConfig


def test_ladder_promote_hold_demote():
    promote = decide_ladder_action("stage_1", final_go=True, severe_fail=False)
    hold = decide_ladder_action("stage2_small", final_go=False, severe_fail=False)
    demote = decide_ladder_action("stage3_scale", final_go=False, severe_fail=True)
    assert promote["action"] == "promote" and promote["next_stage"] == "stage2_small"
    assert hold["action"] == "hold" and hold["next_stage"] == "stage2_small"
    assert demote["action"] == "demote" and demote["next_stage"] == "stage2_small"


def test_ladder_alias_and_caps_resolution():
    assert normalize_stage("stage_1") == "stage1_micro"
    caps = resolve_ladder_caps(stage="stage_2")
    assert caps.stage == "stage2_small"
    assert caps.max_gross_exposure > 0


def test_model_registry_refresh_due(tmp_path):
    cfg = ModelRegistryConfig(
        root=str(tmp_path / "registry"),
        trend_refresh_days=7,
        hmm_refresh_days=7,
        pairs_refresh_days=1,
    )
    register_model_version(
        cfg,
        run_id="r1",
        model_type="trend",
        model_version="v1",
        training_window="2025-01-01..2025-06-01",
        feature_schema_version="f1",
        data_hash="abc",
        artifact_path="models/trend_v1.pkl",
        created_at_utc="2026-01-01T00:00:00+00:00",
    )
    due = refresh_due(cfg, now_utc="2026-01-10T00:00:00+00:00")
    assert due["trend"] is True
    assert due["hmm"] is True
    assert due["pairs"] is True
