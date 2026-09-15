"""Integration tests for Phase 5 walk-forward bundle generation."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from fx_hybrid_engine.evaluation.contract import validate_run_tree
from fx_hybrid_engine.evaluation.parity import verify_parity
from fx_hybrid_engine.evaluation.walkforward import run_walkforward

pytestmark = pytest.mark.integration


def _base_cfg() -> dict:
    cfg_raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    cfg_raw["walkforward"]["data_profile"] = "local_smoke"
    cfg_raw["walkforward"]["auto_report"] = False
    cfg_raw["trend_engine"]["sma_fast"] = 20
    cfg_raw["trend_engine"]["sma_slow"] = 60
    cfg_raw["trend_engine"]["feature_lookback"] = 20
    return cfg_raw


def _smoke_cfg(tmp_path, filename: str) -> Path:
    cfg_raw = _base_cfg()
    cfg_raw["walkforward"]["output_root"] = str(tmp_path / "artifacts")
    cfg_raw["walkforward"]["start_date"] = "2021-01-01"
    cfg_raw["walkforward"]["end_date"] = "2022-12-31"
    cfg_raw["walkforward"]["train_window_days"] = 260
    cfg_raw["walkforward"]["test_window_days"] = 60
    cfg_raw["walkforward"]["step_days"] = 60
    cfg_raw["walkforward"]["max_splits"] = 1
    cfg_raw["robustness"]["param_sweep_samples"] = 0
    cfg_path = tmp_path / filename
    cfg_path.write_text(yaml.safe_dump(cfg_raw, sort_keys=False), encoding="utf-8")
    return cfg_path


def _parity_cfg(tmp_path, filename: str) -> Path:
    cfg_raw = _base_cfg()
    cfg_raw["universe"]["pairs"] = [["EURUSD", "GBPUSD"]]
    cfg_raw["universe"]["trend_symbols"] = ["EURUSD", "GBPUSD"]
    cfg_raw["walkforward"]["output_root"] = str(tmp_path / "artifacts")
    cfg_raw["walkforward"]["start_date"] = "2021-01-01"
    cfg_raw["walkforward"]["end_date"] = "2021-12-31"
    cfg_raw["walkforward"]["train_window_days"] = 120
    cfg_raw["walkforward"]["test_window_days"] = 30
    cfg_raw["walkforward"]["step_days"] = 30
    cfg_raw["walkforward"]["max_splits"] = 1
    cfg_raw["robustness"]["param_sweep_samples"] = 0
    cfg_path = tmp_path / filename
    cfg_path.write_text(yaml.safe_dump(cfg_raw, sort_keys=False), encoding="utf-8")
    return cfg_path


def test_walkforward_bundle_smoke(tmp_path):
    cfg_path = _smoke_cfg(tmp_path, "phase5_smoke.yaml")

    run_dir = run_walkforward(
        config_path=cfg_path,
        wf_run_id="itest_smoke",
        max_splits=1,
        run_report=True,
        skip_robustness=True,
        precompute=True,
        mode_reuse=True,
    )
    assert run_dir.exists()
    assert (run_dir / "run_manifest.json").exists()
    assert (run_dir / "phase5_proof_report.md").exists()
    assert (run_dir / "phase5_report_summary.json").exists()
    assert (run_dir / "pairs_diagnostics_by_split.csv").exists()
    assert (run_dir / "regime_qa_by_split.csv").exists()
    assert (run_dir / "split_000" / "pairs_candidates.csv").exists()
    assert (run_dir / "split_000" / "pairs_scan.csv").exists()
    assert (run_dir / "split_000" / "pairs_diagnostics.csv").exists()
    assert (run_dir / "split_000" / "pair_state_events.csv").exists()
    assert (run_dir / "split_000" / "pair_state_snapshot.json").exists()
    assert (run_dir / "split_000" / "regime_events.csv").exists()
    assert (run_dir / "split_000" / "regime_summary.json").exists()
    assert (run_dir / "split_000" / "hmm_state_map.json").exists()

    metrics = pd.read_csv(run_dir / "metrics_by_split.csv")
    assert set(metrics["mode"].unique()) == {"hybrid", "pairs_only", "trend_only"}
    assert metrics["split_idx"].nunique() == 1
    assert {"precompute_enabled", "mode_reuse_enabled", "cache_fingerprint", "pipeline_version"} <= set(metrics.columns)

    ok, issues = validate_run_tree(run_dir)
    assert ok, "\n".join(i.message for i in issues)


def test_walkforward_parity_matrix_smoke(tmp_path):
    cfg_path = _parity_cfg(tmp_path, "phase5_parity.yaml")
    run_a = run_walkforward(
        config_path=cfg_path,
        wf_run_id="itest_parity_a",
        max_splits=1,
        run_report=False,
        skip_robustness=True,
        precompute=True,
        mode_reuse=True,
    )
    run_b = run_walkforward(
        config_path=cfg_path,
        wf_run_id="itest_parity_b",
        max_splits=1,
        run_report=False,
        skip_robustness=True,
        precompute=False,
        mode_reuse=False,
    )
    run_c = run_walkforward(
        config_path=cfg_path,
        wf_run_id="itest_parity_c",
        max_splits=1,
        run_report=False,
        skip_robustness=True,
        precompute=True,
        mode_reuse=False,
    )

    report_ab = verify_parity(run_a, run_b, profile="local_smoke")
    report_ac = verify_parity(run_a, run_c, profile="local_smoke", output_path=run_a / "parity_report_ac.json")
    assert report_ab["pass"], report_ab
    assert report_ac["pass"], report_ac
    assert (run_a / "parity_report.json").exists()
    assert (run_a / "parity_report_ac.json").exists()
    for run_dir in (run_a, run_b, run_c):
        metrics = pd.read_csv(run_dir / "metrics_by_split.csv")
        assert not metrics.empty
        assert set(metrics["mode"].unique()) == {"hybrid", "pairs_only", "trend_only"}
        for mode in ("hybrid", "pairs_only", "trend_only"):
            assert (run_dir / "split_000" / mode).exists()


@pytest.mark.slow
def test_walkforward_bundle_full(tmp_path):
    cfg_raw = _base_cfg()
    cfg_raw["walkforward"]["output_root"] = str(tmp_path / "artifacts")
    cfg_raw["walkforward"]["start_date"] = "2020-01-01"
    cfg_raw["walkforward"]["end_date"] = "2023-12-31"
    cfg_raw["walkforward"]["train_window_days"] = 240
    cfg_raw["walkforward"]["test_window_days"] = 90
    cfg_raw["walkforward"]["step_days"] = 90
    cfg_raw["walkforward"]["max_splits"] = 2
    cfg_raw["robustness"]["param_sweep_samples"] = 2

    cfg_path = tmp_path / "phase5_full.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg_raw, sort_keys=False), encoding="utf-8")

    run_dir = run_walkforward(
        config_path=cfg_path,
        wf_run_id="itest_full",
        max_splits=2,
        run_report=True,
        skip_robustness=False,
        precompute=True,
        mode_reuse=True,
    )
    assert run_dir.exists()
    assert (run_dir / "robustness_cost_sweep.csv").exists()
    assert (run_dir / "robustness_param_sweep.csv").exists()
    assert (run_dir / "proof_checks.json").exists()

    robust = pd.read_csv(run_dir / "robustness_param_sweep.csv")
    assert not robust.empty

    ok, issues = validate_run_tree(run_dir)
    assert ok, "\n".join(i.message for i in issues)
