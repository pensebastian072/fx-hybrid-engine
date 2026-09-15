"""Shared pytest fixtures."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_cointegrated_pair() -> tuple[pd.Series, pd.Series, float]:
    """Generate two cointegrated price series with a known beta=1.5.

    Returns (price_a, price_b, true_beta).
    """
    rng = np.random.default_rng(42)
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    # Shared random walk
    common = np.cumsum(rng.normal(0, 0.01, n))
    noise_a = rng.normal(0, 0.002, n)
    noise_b = rng.normal(0, 0.002, n)
    true_beta = 1.5
    log_a = common + noise_a
    log_b = (common / true_beta) + noise_b
    price_a = pd.Series(np.exp(log_a + 5), index=dates, name="A")
    price_b = pd.Series(np.exp(log_b + 5), index=dates, name="B")
    return price_a, price_b, true_beta


@pytest.fixture
def synthetic_trending_series() -> pd.DataFrame:
    """Generate a price series with a clear uptrend for 250 bars then flat."""
    rng = np.random.default_rng(7)
    n = 400
    dates = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    trend = np.linspace(100, 150, 250)
    flat = np.full(150, 150.0)
    prices = np.concatenate([trend, flat]) + rng.normal(0, 0.5, n)
    close = pd.Series(prices, index=dates, name="close")
    return pd.DataFrame({"close": close, "open": close, "high": close * 1.001, "low": close * 0.999})


@pytest.fixture
def synthetic_vol_spike_series() -> pd.DataFrame:
    """Generate a series with a clear volatility spike in the second half."""
    rng = np.random.default_rng(13)
    n = 300
    dates = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    low_vol = np.cumsum(rng.normal(0, 0.005, 150))
    high_vol = np.cumsum(rng.normal(0, 0.05, 150))
    log_prices = np.concatenate([low_vol, low_vol[-1] + high_vol])
    prices = np.exp(log_prices + 5)
    close = pd.Series(prices, index=dates, name="close")
    return pd.DataFrame({"close": close, "open": close, "high": close * 1.001, "low": close * 0.999})
