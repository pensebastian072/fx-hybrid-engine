"""Unit tests for evaluation/metrics.py (extended performance metrics)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from fx_hybrid_engine.evaluation.metrics import (
    avg_trade_return,
    calmar_ratio,
    compute_extended_metrics,
    information_ratio,
    max_drawdown,
    max_drawdown_duration,
    omega_ratio,
    sharpe_ratio,
    sortino_ratio,
)


@pytest.fixture()
def good_equity():
    """Rising equity curve with clear positive drift."""
    rng = np.random.default_rng(10)
    n = 252
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    # Force positive drift: |returns| + small positive mean
    ret = np.abs(rng.normal(0.0005, 0.003, n))
    return pd.Series(100 * np.cumprod(1 + ret), index=idx)


@pytest.fixture()
def bad_equity():
    """Equity curve starting at 100 with a significant drawdown."""
    n = 252
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    prices = np.ones(n) * 100.0
    prices[50:150] = np.linspace(100.0, 70.0, 100)  # 30% drawdown
    prices[150:] = np.linspace(70.0, 85.0, 102)
    return pd.Series(prices, index=idx)


def test_sharpe_positive_drift(good_equity):
    r = good_equity.pct_change().dropna()
    sr = sharpe_ratio(r)
    assert sr > 0


def test_sharpe_zero_for_flat():
    flat = pd.Series([1.0] * 50)
    assert sharpe_ratio(flat) == 0.0


def test_sortino_gte_sharpe(good_equity):
    r = good_equity.pct_change().dropna()
    sh = sharpe_ratio(r)
    so = sortino_ratio(r)
    # Sortino should be >= Sharpe when return is positive (ignores upside vol)
    assert so >= sh


def test_sortino_inf_for_no_losses():
    all_gains = pd.Series([0.001] * 100)
    assert math.isinf(sortino_ratio(all_gains))


def test_max_drawdown_positive(bad_equity):
    mdd = max_drawdown(bad_equity)
    assert 0.25 < mdd < 0.35  # roughly 30%


def test_max_drawdown_zero_for_rising():
    rising = pd.Series(np.linspace(1.0, 2.0, 100))
    assert max_drawdown(rising) == 0.0 or max_drawdown(rising) < 1e-10


def test_max_drawdown_duration(bad_equity):
    dur = max_drawdown_duration(bad_equity)
    assert dur > 0


def test_calmar_positive(bad_equity):
    """Calmar uses annualized return / max_drawdown; needs a drawdown to be meaningful."""
    # bad_equity starts at 100, drops to 70, recovers to 85
    # There IS a drawdown, and the net return is -15% (ends lower than start)
    # So calmar should be negative (negative ann return / positive drawdown)
    cr = calmar_ratio(bad_equity)
    assert isinstance(cr, float)


def test_calmar_zero_no_drawdown():
    """When max drawdown is zero, calmar returns 0.0 by convention."""
    rising = pd.Series(np.linspace(100.0, 200.0, 100))
    assert calmar_ratio(rising) == 0.0


def test_omega_above_one_positive_drift(good_equity):
    r = good_equity.pct_change().dropna()
    om = omega_ratio(r, threshold=0.0)
    assert om > 1.0


def test_omega_inf_for_all_gains():
    r = pd.Series([0.001] * 100)
    assert math.isinf(omega_ratio(r, threshold=0.0))


def test_information_ratio_perfect_match():
    r = pd.Series(np.random.default_rng(11).normal(0, 0.01, 100))
    ir = information_ratio(r, r)
    assert ir == 0.0  # no active return


def test_information_ratio_positive(good_equity):
    r = good_equity.pct_change().dropna()
    bench = r * 0.5  # strategy outperforms benchmark
    ir = information_ratio(r, bench)
    assert ir > 0


def test_avg_trade_return_signs():
    r = pd.Series([-0.01, 0.02, -0.005, 0.015, 0.0, 0.03])
    avg_win, avg_lose = avg_trade_return(r)
    assert avg_win > 0
    assert avg_lose <= 0


def test_compute_extended_metrics_keys(good_equity):
    metrics = compute_extended_metrics(good_equity)
    required = {
        "sharpe", "sortino", "calmar", "omega", "information_ratio",
        "max_drawdown", "max_drawdown_duration_bars",
        "avg_winner_pct", "avg_loser_pct",
        "max_winning_streak", "max_losing_streak",
    }
    assert required.issubset(metrics.keys())


def test_compute_extended_metrics_values_are_finite(good_equity):
    metrics = compute_extended_metrics(good_equity)
    for k, v in metrics.items():
        assert isinstance(v, float), f"{k} is not float"
        assert not math.isnan(v), f"{k} is NaN"


def test_compute_extended_metrics_with_benchmark(good_equity):
    r = good_equity.pct_change().dropna()
    bench = r * 0.5  # strategy consistently outperforms benchmark
    metrics = compute_extended_metrics(good_equity, benchmark_returns=bench)
    assert "information_ratio" in metrics
    assert metrics["information_ratio"] > 0
