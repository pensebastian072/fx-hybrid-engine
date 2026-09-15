"""Unit tests for VolatilityRegimeClassifier (regime/volatility_classifier.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fx_hybrid_engine.regime.volatility_classifier import (
    VolRegime,
    VolatilityRegimeClassifier,
    VOL_REGIME_HIGH,
    VOL_REGIME_LOW,
    VOL_REGIME_MED,
)


@pytest.fixture()
def calm_volatile_series():
    """Series: first half calm, second half volatile."""
    rng = np.random.default_rng(5)
    n = 200
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    calm = np.cumsum(rng.normal(0, 0.001, n // 2))
    volatile = np.cumsum(rng.normal(0, 0.02, n // 2))
    prices = pd.Series(
        1.1 + np.concatenate([calm, calm[-1] + volatile]),
        index=idx,
    )
    return prices


def test_not_fitted_initially():
    clf = VolatilityRegimeClassifier()
    assert not clf.is_fitted


def test_fit_sets_thresholds(calm_volatile_series):
    clf = VolatilityRegimeClassifier(vol_window=20)
    clf.fit(calm_volatile_series)
    assert clf.is_fitted
    assert clf._thresh_low is not None
    assert clf._thresh_high is not None
    assert clf._thresh_low < clf._thresh_high


def test_classify_series_returns_series(calm_volatile_series):
    clf = VolatilityRegimeClassifier(vol_window=20)
    clf.fit(calm_volatile_series)
    result = clf.classify_series(calm_volatile_series)
    assert isinstance(result, pd.Series)
    assert len(result) == len(calm_volatile_series)


def test_classify_series_valid_regimes(calm_volatile_series):
    clf = VolatilityRegimeClassifier(vol_window=20)
    clf.fit(calm_volatile_series)
    result = clf.classify_series(calm_volatile_series)
    valid = {VolRegime.LOW, VolRegime.MED, VolRegime.HIGH}
    assert set(result.dropna().unique()).issubset(valid)


def test_high_vol_second_half(calm_volatile_series):
    """Volatile second half should produce more HIGH_VOL classifications."""
    clf = VolatilityRegimeClassifier(vol_window=20)
    clf.fit(calm_volatile_series)
    regimes = clf.classify_series(calm_volatile_series)
    first_half = regimes.iloc[:80]
    second_half = regimes.iloc[120:]
    high_first = (first_half == VolRegime.HIGH).sum()
    high_second = (second_half == VolRegime.HIGH).sum()
    assert high_second > high_first


def test_classify_bar_returns_vol_regime(calm_volatile_series):
    clf = VolatilityRegimeClassifier(vol_window=20)
    clf.fit(calm_volatile_series)
    regime = clf.classify_bar(calm_volatile_series)
    assert isinstance(regime, VolRegime)


def test_classify_bar_without_fit_returns_med():
    clf = VolatilityRegimeClassifier(vol_window=20)
    rng = np.random.default_rng(6)
    prices = pd.Series(1.0 + np.cumsum(rng.normal(0, 0.001, 50)))
    result = clf.classify_bar(prices)
    assert result == VolRegime.MED


def test_current_vol_is_float(calm_volatile_series):
    clf = VolatilityRegimeClassifier(vol_window=20)
    vol = clf.current_vol(calm_volatile_series)
    assert vol is None or isinstance(vol, float)


def test_summary_keys(calm_volatile_series):
    clf = VolatilityRegimeClassifier(vol_window=20, percentile_low=25, percentile_high=75)
    clf.fit(calm_volatile_series)
    s = clf.summary()
    for key in ("vol_window", "thresh_low", "thresh_high", "fitted"):
        assert key in s
    assert s["fitted"] is True


def test_vol_regime_constants():
    assert VOL_REGIME_LOW == "LOW_VOL"
    assert VOL_REGIME_MED == "MED_VOL"
    assert VOL_REGIME_HIGH == "HIGH_VOL"
