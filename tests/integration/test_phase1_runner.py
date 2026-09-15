"""Integration tests for Phase 1 verification runner."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from fx_hybrid_engine.evaluation.phase1_runner import run_phase1
from fx_hybrid_engine.ops.schema import validate_ops_run_dir

pytestmark = pytest.mark.integration


def _phase1_cfg(tmp_path: Path) -> Path:
    raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    raw["ops"]["output_root"] = str(tmp_path / "outputs")
    raw["data"]["source"] = "lean_history"
    raw["data"]["bar_frequency"] = "15m"
    raw["universe"]["pairs"] = [["EURUSD", "GBPUSD"]]
    raw["universe"]["trend_symbols"] = ["EURUSD", "GBPUSD"]
    raw["trend_engine"]["sma_fast"] = 20
    raw["trend_engine"]["sma_slow"] = 60
    cfg_path = tmp_path / "phase1.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return cfg_path


def test_phase1_smoke_emits_contract_artifacts(tmp_path):
    cfg_path = _phase1_cfg(tmp_path)
    run_dir = run_phase1(config_path=cfg_path, profile="smoke", run_id="itest_phase1")
    assert run_dir.exists()
    assert (run_dir / "run_manifest.json").exists()
    assert (run_dir / "config_snapshot.yaml").exists()
    assert (run_dir / "bar_health.csv").exists()
    assert (run_dir / "metrics.json").exists()

    health = pd.read_csv(run_dir / "bar_health.csv")
    assert {"symbol", "target_frequency", "gap_count", "rows_output"} <= set(health.columns)

    ok, issues = validate_ops_run_dir(run_dir, require_run_id_columns=True, strict_append_audit=True)
    assert ok, "\n".join(i.message for i in issues)


def test_phase1_provider_mismatch_fails_fast(tmp_path):
    cfg_path = _phase1_cfg(tmp_path)
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    raw["data"]["source"] = "openbb"
    raw["data"]["bar_frequency"] = "15m"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="does not support bar frequency"):
        run_phase1(config_path=cfg_path, profile="smoke", run_id="itest_phase1_bad_source")
