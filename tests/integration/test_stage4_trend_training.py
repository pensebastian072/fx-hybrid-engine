from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from fx_hybrid_engine.evaluation.contract import validate_run_tree
from fx_hybrid_engine.evaluation.trend_dataset import build_trend_dataset
from fx_hybrid_engine.evaluation.trend_training import train_trend_walkforward
from fx_hybrid_engine.evaluation.walkforward import run_walkforward

pytestmark = pytest.mark.integration


def _cfg(tmp_path: Path) -> Path:
    raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    raw["data"]["source"] = "lean_history"
    raw["data"]["bar_frequency"] = "15m"
    raw["walkforward"]["start_date"] = "2024-01-01"
    raw["walkforward"]["end_date"] = "2024-03-01"
    raw["walkforward"]["output_root"] = str(tmp_path / "wf")
    raw["walkforward"]["max_splits"] = 1
    raw["walkforward"]["train_window_days"] = 30
    raw["walkforward"]["test_window_days"] = 10
    raw["walkforward"]["step_days"] = 10
    raw["universe"]["trend_symbols"] = ["EURUSD", "GBPUSD"]
    raw["trend_engine"]["sma_fast"] = 20
    raw["trend_engine"]["sma_slow"] = 60
    raw["trend_engine"]["feature_lookback"] = 20
    raw["trend_engine"]["label_horizon_bars"] = 4
    raw["trend_engine"]["label_threshold_bps"] = 2.0
    raw["trend_engine"]["min_train_rows"] = 100
    raw["trend_engine"]["train_window_days"] = 30
    raw["trend_engine"]["test_window_days"] = 10
    raw["trend_engine"]["step_days"] = 10
    raw["trend_engine"]["model_root"] = str(tmp_path / "models")
    raw["trend_engine"]["model_version"] = "itest_model_v1"
    cfg_path = tmp_path / "stage4_cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return cfg_path


def test_stage4_training_and_walkforward_uses_model_version(tmp_path):
    cfg_path = _cfg(tmp_path)
    ds_res = build_trend_dataset(
        config_path=cfg_path,
        output_dir=tmp_path / "dataset",
        run_id="itest_ds",
    )
    train_res = train_trend_walkforward(
        config_path=cfg_path,
        model_version="itest_model_v1",
        dataset_path=ds_res["dataset_path"],
        output_root=tmp_path / "models",
    )
    assert Path(train_res["model_path"]).exists()

    run_dir = run_walkforward(
        config_path=cfg_path,
        wf_run_id="itest_wf_stage4",
        max_splits=1,
        run_report=False,
        skip_robustness=True,
        precompute=True,
        mode_reuse=True,
    )
    metrics = pd.read_csv(run_dir / "metrics_by_split.csv")
    assert "trend_model_version" in metrics.columns
    assert set(metrics["trend_model_version"].dropna().astype(str).unique()) == {"itest_model_v1"}
    ok, issues = validate_run_tree(run_dir)
    assert ok, "\n".join(i.message for i in issues)
