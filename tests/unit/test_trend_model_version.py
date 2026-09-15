from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from fx_hybrid_engine.contracts import SCHEMA_VERSION
from fx_hybrid_engine.engines.trend import TrendEngine
from fx_hybrid_engine.engines.trend_features import feature_columns, feature_schema_hash
from fx_hybrid_engine.utils.config import TrendConfig


def _make_model():
    X = np.asarray([[0.0, 0.1, 50.0, 0.2, 0.001], [0.1, -0.1, 45.0, 0.3, -0.001]])
    y = np.asarray([1, 0])
    model = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=1000, random_state=42))])
    model.fit(X, y)
    return model


def _write_versioned_artifact(root: Path, cfg: TrendConfig, version: str, schema_hash: str) -> Path:
    vdir = root / version
    vdir.mkdir(parents=True, exist_ok=True)
    joblib.dump(_make_model(), vdir / "trend_model.joblib")
    metadata = {
        "model_version": version,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_commit": "unknown",
        "config_hash": "a" * 64,
        "schema_version": SCHEMA_VERSION,
        "feature_schema_hash": schema_hash,
        "feature_columns": feature_columns(cfg),
        "label_mode": "binary",
        "label_horizon_bars": 8,
        "label_threshold_bps": 6.0,
        "train_window_days": 270,
        "test_window_days": 60,
        "step_days": 30,
        "seed": 42,
        "data_hash": "b" * 64,
        "symbols": ["EURUSD"],
        "bar_frequency": "15m",
        "model_family": "logreg",
    }
    (vdir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return vdir


def test_load_model_version_success(tmp_path):
    cfg = TrendConfig(model_root=str(tmp_path), model_version="latest", sma_fast=20, sma_slow=60, feature_lookback=20)
    _write_versioned_artifact(tmp_path, cfg, "v1", feature_schema_hash(cfg))
    engine = TrendEngine(cfg)
    assert engine.load_model_version()
    assert engine.model_version == "v1"


def test_load_model_version_schema_mismatch_raises(tmp_path):
    cfg = TrendConfig(model_root=str(tmp_path), model_version="latest", sma_fast=20, sma_slow=60, feature_lookback=20)
    _write_versioned_artifact(tmp_path, cfg, "v1", "deadbeef" * 8)
    engine = TrendEngine(cfg)
    try:
        engine.load_model_version()
    except ValueError as exc:
        assert "schema mismatch" in str(exc)
    else:
        raise AssertionError("Expected schema mismatch ValueError")
