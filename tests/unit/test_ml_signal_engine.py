"""Unit tests for MLSignalEngine (engines/ml_signal.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fx_hybrid_engine.engines.ml_signal import MLSignalEngine
from fx_hybrid_engine.engines.types import Direction, EngineType
from fx_hybrid_engine.utils.config import MLSignalConfig


@pytest.fixture()
def synthetic_data():
    """Synthetic OHLCV data for a single symbol."""
    rng = np.random.default_rng(1)
    n = 800
    idx = pd.date_range("2020-01-01", periods=n, freq="h")
    close = pd.Series(1.1 + np.cumsum(rng.normal(0, 0.001, n)), index=idx)
    df = pd.DataFrame(
        {
            "close": close.values,
            "open": (close * (1 + rng.uniform(-0.0005, 0.0005, n))).values,
            "high": (close * (1 + rng.uniform(0, 0.002, n))).values,
            "low": (close * (1 - rng.uniform(0, 0.002, n))).values,
            "volume": rng.integers(1000, 5000, n).astype(float),
        },
        index=idx,
    )
    return df


@pytest.fixture()
def small_config():
    return MLSignalConfig(
        n_estimators=20,
        max_depth=3,
        min_train_rows=300,
        use_xgboost=False,  # RF only for speed
        use_advanced_features=True,
        seed=42,
    )


def test_engine_type():
    config = MLSignalConfig()
    engine = MLSignalEngine(config)
    # Engine generates ML_ENSEMBLE signals
    assert EngineType.ML_ENSEMBLE == EngineType.ML_ENSEMBLE


def test_engine_not_fitted_initially(small_config):
    engine = MLSignalEngine(small_config)
    assert not engine.is_fitted


def test_train_succeeds(small_config, synthetic_data):
    engine = MLSignalEngine(small_config)
    engine.train({"EURUSD": synthetic_data})
    assert engine.is_fitted


def test_generate_returns_engine_output(small_config, synthetic_data):
    engine = MLSignalEngine(small_config)
    engine.train({"EURUSD": synthetic_data})
    ts = pd.Timestamp("2021-01-01", tz="UTC")
    output = engine.generate({"EURUSD": synthetic_data}, ts)
    assert output.engine == EngineType.ML_ENSEMBLE
    assert output.timestamp == ts
    assert len(output.signals) == 1


def test_generate_signal_direction_valid(small_config, synthetic_data):
    engine = MLSignalEngine(small_config)
    engine.train({"EURUSD": synthetic_data})
    ts = pd.Timestamp("2021-01-01", tz="UTC")
    output = engine.generate({"EURUSD": synthetic_data}, ts)
    sig = output.signals[0]
    assert sig.direction in (Direction.LONG, Direction.SHORT, Direction.FLAT)
    assert 0.0 <= sig.confidence <= 1.0


def test_generate_flat_without_training(small_config, synthetic_data):
    engine = MLSignalEngine(small_config)
    ts = pd.Timestamp("2021-01-01", tz="UTC")
    output = engine.generate({"EURUSD": synthetic_data}, ts)
    assert output.signals[0].direction == Direction.FLAT


def test_generate_flat_for_short_data(small_config):
    engine = MLSignalEngine(small_config)
    rng = np.random.default_rng(2)
    short_df = pd.DataFrame({"close": rng.normal(1.1, 0.001, 10)})
    ts = pd.Timestamp("2021-01-01", tz="UTC")
    output = engine.generate({"EURUSD": short_df}, ts)
    assert output.signals[0].direction == Direction.FLAT


def test_train_skips_insufficient_symbols(small_config):
    engine = MLSignalEngine(small_config)
    rng = np.random.default_rng(3)
    tiny = pd.DataFrame({"close": rng.normal(1.1, 0.001, 5)})
    with pytest.raises(ValueError, match="No usable training data"):
        engine.train({"EURUSD": tiny})


def test_feature_columns_list(small_config):
    engine = MLSignalEngine(small_config)
    cols = engine.feature_columns
    assert isinstance(cols, list)
    assert len(cols) > 0
    assert "log_return" in cols
    assert "bb_pct_b" in cols  # advanced features on by default


def test_save_and_load(tmp_path, small_config, synthetic_data):
    engine = MLSignalEngine(small_config)
    engine.train({"EURUSD": synthetic_data})
    out_dir = engine.save(version_dir=tmp_path / "v1")
    assert (out_dir / "ml_signal_model.joblib").exists()
    assert (out_dir / "metadata.json").exists()

    engine2 = MLSignalEngine(small_config)
    ok = engine2.load(version_dir=out_dir)
    assert ok
    assert engine2.is_fitted

    ts = pd.Timestamp("2021-01-01", tz="UTC")
    output = engine2.generate({"EURUSD": synthetic_data}, ts)
    assert output.signals[0].direction in (Direction.LONG, Direction.SHORT, Direction.FLAT)
