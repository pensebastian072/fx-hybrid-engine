from __future__ import annotations

import numpy as np
import pandas as pd

from fx_hybrid_engine.engines.trend_features import (
    compute_trend_features,
    feature_columns,
    feature_schema_hash,
)
from fx_hybrid_engine.utils.config import TrendConfig


def test_feature_schema_hash_is_stable():
    cfg = TrendConfig(sma_fast=20, sma_slow=60, feature_lookback=20)
    assert feature_schema_hash(cfg) == feature_schema_hash(cfg)


def test_feature_schema_hash_changes_with_config():
    a = TrendConfig(sma_fast=20, sma_slow=60, feature_lookback=20)
    b = TrendConfig(sma_fast=30, sma_slow=60, feature_lookback=20)
    assert feature_schema_hash(a) != feature_schema_hash(b)


def test_compute_trend_features_contains_required_columns():
    idx = pd.date_range("2024-01-01", periods=300, freq="D", tz="UTC")
    close = pd.Series(1.0 + np.linspace(0.0, 0.1, len(idx)), index=idx)
    cfg = TrendConfig(sma_fast=20, sma_slow=60, feature_lookback=20)
    feats = compute_trend_features(close, cfg)
    for col in feature_columns(cfg):
        assert col in feats.columns
