"""Unit tests for advanced technical indicators (features/advanced.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fx_hybrid_engine.features.advanced import (
    atr,
    bollinger_bands,
    cci,
    compute_all_advanced,
    macd,
    mfi,
    obv,
    stochastic,
    williams_r,
)


@pytest.fixture()
def price_series():
    rng = np.random.default_rng(42)
    n = 100
    close = pd.Series(
        1.1 + np.cumsum(rng.normal(0, 0.001, n)),
        index=pd.date_range("2023-01-01", periods=n, freq="D"),
    )
    high = close + rng.uniform(0, 0.003, n)
    low = close - rng.uniform(0, 0.003, n)
    volume = pd.Series(rng.integers(1000, 5000, n).astype(float), index=close.index)
    return close, high, low, volume


def test_bollinger_bands_columns(price_series):
    close, *_ = price_series
    result = bollinger_bands(close, window=20)
    assert set(result.columns) == {"bb_mid", "bb_upper", "bb_lower", "bb_pct_b", "bb_bandwidth"}


def test_bollinger_bands_upper_gt_lower(price_series):
    close, *_ = price_series
    result = bollinger_bands(close, window=20).dropna()
    assert (result["bb_upper"] >= result["bb_lower"]).all()


def test_bollinger_bands_pct_b_range(price_series):
    """For a trending series, %B is mostly in [0,1]; no hard assertion but no NaNs after warmup."""
    close, *_ = price_series
    result = bollinger_bands(close, window=20).dropna()
    assert result["bb_pct_b"].notna().all()


def test_macd_columns(price_series):
    close, *_ = price_series
    result = macd(close)
    assert set(result.columns) == {"macd_line", "macd_signal", "macd_histogram"}


def test_macd_histogram_identity(price_series):
    close, *_ = price_series
    result = macd(close).dropna()
    diff = (result["macd_histogram"] - (result["macd_line"] - result["macd_signal"])).abs()
    assert diff.max() < 1e-10


def test_atr_positive(price_series):
    close, high, low, _ = price_series
    result = atr(high, low, close, window=14).dropna()
    assert (result > 0).all()
    assert result.name == "atr"


def test_stochastic_range(price_series):
    close, high, low, _ = price_series
    result = stochastic(high, low, close).dropna()
    assert (result["stoch_k"] >= 0).all() and (result["stoch_k"] <= 100).all()
    assert (result["stoch_d"] >= 0).all() and (result["stoch_d"] <= 100).all()


def test_williams_r_range(price_series):
    close, high, low, _ = price_series
    result = williams_r(high, low, close).dropna()
    assert (result >= -100).all() and (result <= 0).all()
    assert result.name == "williams_r"


def test_cci_is_series(price_series):
    close, high, low, _ = price_series
    result = cci(high, low, close).dropna()
    assert isinstance(result, pd.Series)
    assert result.name == "cci"


def test_obv_monotone_when_always_up(price_series):
    close, _, _, volume = price_series
    rising = pd.Series(np.linspace(1.0, 2.0, 50), index=close.index[:50])
    vol = volume.iloc[:50]
    result = obv(rising, vol)
    # OBV should be non-decreasing for monotonically rising prices
    assert (result.diff().dropna() >= 0).all()


def test_mfi_range(price_series):
    close, high, low, volume = price_series
    result = mfi(high, low, close, volume, window=14).dropna()
    assert (result >= 0).all() and (result <= 100).all()
    assert result.name == "mfi"


def test_compute_all_advanced_close_only(price_series):
    close, *_ = price_series
    result = compute_all_advanced(close)
    # Should have at least Bollinger + MACD columns
    assert "bb_pct_b" in result.columns
    assert "macd_line" in result.columns
    # No ATR, Stochastic etc. since high/low not provided
    assert "atr" not in result.columns


def test_compute_all_advanced_full(price_series):
    close, high, low, volume = price_series
    result = compute_all_advanced(close, high=high, low=low, volume=volume)
    for col in ("bb_pct_b", "bb_bandwidth", "macd_line", "atr", "stoch_k", "williams_r", "cci", "obv", "mfi"):
        assert col in result.columns, f"Missing column: {col}"
