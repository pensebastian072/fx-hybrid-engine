from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from fx_hybrid_engine.evaluation.trend_dataset import build_trend_dataset
from fx_hybrid_engine.evaluation.trend_training import train_trend_walkforward


def _make_cfg(tmp_path: Path) -> Path:
    raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    raw["data"]["source"] = "lean_history"
    raw["data"]["bar_frequency"] = "15m"
    raw["universe"]["trend_symbols"] = ["EURUSD"]
    raw["walkforward"]["start_date"] = "2024-01-01"
    raw["walkforward"]["end_date"] = "2024-02-15"
    raw["trend_engine"]["sma_fast"] = 10
    raw["trend_engine"]["sma_slow"] = 20
    raw["trend_engine"]["feature_lookback"] = 10
    raw["trend_engine"]["label_horizon_bars"] = 4
    raw["trend_engine"]["label_threshold_bps"] = 2.0
    raw["trend_engine"]["min_train_rows"] = 50
    raw["trend_engine"]["train_window_days"] = 20
    raw["trend_engine"]["test_window_days"] = 10
    raw["trend_engine"]["step_days"] = 10
    raw["trend_engine"]["model_root"] = str(tmp_path / "models")
    cfg_path = tmp_path / "trend_cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return cfg_path


def test_build_trend_dataset_outputs_expected_files(tmp_path):
    cfg_path = _make_cfg(tmp_path)
    out_dir = tmp_path / "dataset"
    result = build_trend_dataset(config_path=cfg_path, output_dir=out_dir, run_id="unit_ds")
    ds = pd.read_parquet(result["dataset_path"])
    assert not ds.empty
    assert {"timestamp", "symbol", "forward_return", "label"} <= set(ds.columns)
    assert int(ds.isna().sum().sum()) == 0
    stats = json.loads(Path(result["stats_path"]).read_text(encoding="utf-8"))
    assert stats["label_mode"] == "binary"
    assert stats["rows"] == len(ds)


def test_train_trend_walkforward_writes_versioned_artifacts(tmp_path):
    cfg_path = _make_cfg(tmp_path)
    dataset_dir = tmp_path / "dataset_train"
    ds_result = build_trend_dataset(config_path=cfg_path, output_dir=dataset_dir, run_id="unit_train_ds")
    train_result = train_trend_walkforward(
        config_path=cfg_path,
        model_version="unit_model_v1",
        dataset_path=ds_result["dataset_path"],
        output_root=tmp_path / "models_out",
    )
    model_dir = Path(train_result["model_dir"])
    assert (model_dir / "trend_model.joblib").exists()
    assert (model_dir / "metadata.json").exists()
    assert (model_dir / "metrics_by_split.csv").exists()
    assert (model_dir / "oos_summary.json").exists()
    metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
    for key in [
        "model_version",
        "feature_schema_hash",
        "feature_columns",
        "label_mode",
        "data_hash",
        "model_family",
    ]:
        assert key in metadata
