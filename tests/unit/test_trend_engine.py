"""Unit tests for engines/trend.py."""
from __future__ import annotations
import pandas as pd
import pytest

from fx_hybrid_engine.engines.trend import TrendEngine
from fx_hybrid_engine.engines.types import Direction, EngineType
from fx_hybrid_engine.utils.config import TrendConfig


def _make_cfg() -> TrendConfig:
    return TrendConfig(feature_lookback=20, signal_threshold=0.60, sma_fast=20, sma_slow=50)


def test_trend_engine_ma_fallback_long(synthetic_trending_series):
    """MA crossover fallback: a clear uptrend should yield a LONG signal."""
    df = synthetic_trending_series
    cfg = _make_cfg()
    engine = TrendEngine(cfg)
    # Slice to the uptrending portion so fast SMA > slow SMA
    df = df.iloc[:250]
    # No model loaded → fallback
    data = {"EURUSD": df}
    timestamp = df.index[-1]
    output = engine.generate(data, timestamp)
    assert output.engine == EngineType.TREND
    signals = {s.symbol: s for s in output.signals}
    assert "EURUSD" in signals
    # In a strong uptrend with fast SMA > slow SMA, expect LONG
    assert signals["EURUSD"].direction == Direction.LONG


def test_trend_engine_train_and_infer(synthetic_trending_series):
    """Smoke test: train on data and call generate without error."""
    df = synthetic_trending_series
    cfg = _make_cfg()
    engine = TrendEngine(cfg)
    data = {"EURUSD": df}
    engine.train(data)
    assert engine._model is not None
    timestamp = df.index[-1]
    output = engine.generate(data, timestamp)
    assert len(output.signals) == 1
    assert output.signals[0].symbol == "EURUSD"


def test_trend_engine_output_type(synthetic_trending_series):
    df = synthetic_trending_series
    cfg = _make_cfg()
    engine = TrendEngine(cfg)
    output = engine.generate({"EURUSD": df}, df.index[-1])
    assert output.engine == EngineType.TREND
    for sig in output.signals:
        assert sig.direction in Direction.__members__.values()
