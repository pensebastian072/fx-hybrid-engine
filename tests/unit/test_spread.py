"""Unit tests for features/spread.py."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from fx_hybrid_engine.features.spread import (
    compute_spread,
    engle_granger_test,
    hedge_ratio,
    is_cointegrated,
    zscore,
)


def test_compute_spread_known_beta(synthetic_cointegrated_pair):
    price_a, price_b, true_beta = synthetic_cointegrated_pair
    spread = compute_spread(price_a, price_b, true_beta)
    assert isinstance(spread, pd.Series)
    assert len(spread) == len(price_a)
    # Spread should be near-stationary (small std relative to series)
    assert spread.std() < 1.0


def test_zscore_bounds(synthetic_cointegrated_pair):
    price_a, price_b, true_beta = synthetic_cointegrated_pair
    spread = compute_spread(price_a, price_b, true_beta)
    z = zscore(spread, window=60)
    z_valid = z.dropna()
    # Z-scores of a near-stationary spread should be mostly within ±4
    assert (z_valid.abs() < 4).mean() > 0.95


def test_engle_granger_cointegrated(synthetic_cointegrated_pair):
    price_a, price_b, true_beta = synthetic_cointegrated_pair
    stat, pval = engle_granger_test(price_a, price_b)
    assert pval < 0.05, f"Expected cointegrated pair, got p={pval:.4f}"


def test_hedge_ratio_close_to_true(synthetic_cointegrated_pair):
    price_a, price_b, true_beta = synthetic_cointegrated_pair
    estimated = hedge_ratio(price_a, price_b)
    assert abs(estimated - true_beta) < 0.5, f"Hedge ratio {estimated:.3f} far from true {true_beta}"


def test_is_cointegrated_returns_bool(synthetic_cointegrated_pair):
    price_a, price_b, _ = synthetic_cointegrated_pair
    result, pval = is_cointegrated(price_a, price_b)
    assert isinstance(result, bool)
    assert 0 <= pval <= 1
