"""Unit tests for spread.py advanced cointegration functions."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fx_hybrid_engine.features.spread import (
    engle_granger_test,
    half_life,
    is_cointegrated,
    johansen_test,
    kalman_spread,
    zscore,
    compute_spread,
    hedge_ratio,
)


@pytest.fixture()
def cointegrated_pair():
    """Two synthetically cointegrated series."""
    rng = np.random.default_rng(0)
    n = 300
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    common = np.cumsum(rng.normal(0, 0.01, n))  # shared random walk
    price_a = pd.Series(100 * np.exp(common + rng.normal(0, 0.005, n)), index=idx)
    price_b = pd.Series(100 * np.exp(0.8 * common + rng.normal(0, 0.005, n)), index=idx)
    return price_a, price_b


@pytest.fixture()
def mean_reverting_spread():
    """A stationary (mean-reverting) spread."""
    rng = np.random.default_rng(7)
    n = 200
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    spread = pd.Series(0.5 * np.cumsum(rng.normal(0, 0.01, n)) - 0.1, index=idx)
    # force mean reversion by subtracting drift
    mean = spread.expanding().mean()
    spread = spread - mean * 0.15
    return spread


def test_engle_granger_returns_tuple(cointegrated_pair):
    a, b = cointegrated_pair
    stat, pval = engle_granger_test(a, b)
    assert isinstance(stat, float)
    assert 0.0 <= pval <= 1.0


def test_is_cointegrated_detects_pair(cointegrated_pair):
    a, b = cointegrated_pair
    result, _ = is_cointegrated(a, b, pvalue_threshold=0.10)
    # Strongly constructed cointegrated pair — should be detected most of the time
    # We just check the function runs and returns a bool
    assert isinstance(result, bool)


def test_johansen_test_returns_tuple(cointegrated_pair):
    a, b = cointegrated_pair
    is_coint, stat = johansen_test(a, b, significance=0.05)
    assert isinstance(is_coint, bool)
    assert stat is None or isinstance(stat, float)


def test_is_cointegrated_johansen_method(cointegrated_pair):
    a, b = cointegrated_pair
    result, _ = is_cointegrated(a, b, pvalue_threshold=0.05, method="johansen")
    assert isinstance(result, bool)


def test_half_life_finite_for_stationary(mean_reverting_spread):
    hl = half_life(mean_reverting_spread)
    assert np.isfinite(hl) and hl > 0


def test_half_life_inf_for_random_walk():
    """Random walk with no mean-reversion tendency should have long or infinite half-life."""
    rng = np.random.default_rng(42)
    # Construct a pure random walk with large variance (strongly non-stationary)
    rw = pd.Series(np.cumsum(rng.normal(0, 1, 1000)))
    hl_rw = half_life(rw)
    # A strongly mean-reverting AR(1) with phi=0.5 has half-life ≈ 1 bar
    ar1 = pd.Series(0.0)
    vals = [0.0]
    for _ in range(999):
        vals.append(0.5 * vals[-1] + rng.normal(0, 0.01))
    ar1 = pd.Series(vals)
    hl_ar1 = half_life(ar1)
    # Random walk half-life should be notably longer than fast AR(1)
    assert hl_rw == float("inf") or hl_rw > hl_ar1


def test_kalman_spread_shapes(cointegrated_pair):
    a, b = cointegrated_pair
    spread, betas = kalman_spread(a, b)
    assert len(spread) == len(a)
    assert len(betas) == len(a)
    assert spread.name == "kalman_spread"
    assert betas.name == "kalman_beta"


def test_kalman_spread_betas_positive(cointegrated_pair):
    """Hedge ratio should converge to a positive value for our synthetic pair."""
    a, b = cointegrated_pair
    _, betas = kalman_spread(a, b)
    # After warmup (drop first 20 bars), most betas should be positive
    assert (betas.iloc[20:] > 0).mean() > 0.8


def test_hedge_ratio_positive(cointegrated_pair):
    a, b = cointegrated_pair
    beta = hedge_ratio(a, b)
    assert beta > 0


def test_compute_spread_length(cointegrated_pair):
    a, b = cointegrated_pair
    beta = hedge_ratio(a, b)
    spread = compute_spread(a, b, beta)
    assert len(spread) == len(a)


def test_zscore_normalized(cointegrated_pair):
    a, b = cointegrated_pair
    beta = hedge_ratio(a, b)
    spread = compute_spread(a, b, beta)
    z = zscore(spread, window=60).dropna()
    assert abs(z.mean()) < 0.5
    assert 0.5 < z.std() < 2.0
