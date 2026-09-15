"""Cointegration testing, hedge ratio estimation, spread and z-score computation.

Extended in ML4T integration with:
- johansen_test(): Johansen cointegration as alternative to Engle-Granger
- kalman_spread(): dynamic hedge ratio via Kalman filter
- half_life(): Ornstein-Uhlenbeck mean-reversion half-life

Concepts adapted from stefan-jansen/machine-learning-for-trading ch9
(09_time_series_models/05_cointegration_tests.ipynb,
 06_statistical_arbitrage_with_cointegrated_pairs.ipynb).
"""
from __future__ import annotations
import logging
import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from statsmodels.tsa.stattools import coint

logger = logging.getLogger("fxhe.features.spread")


def engle_granger_test(price_a: pd.Series, price_b: pd.Series) -> tuple[float, float]:
    """Run Engle-Granger cointegration test on log prices.

    Returns
    -------
    (test_stat, p_value)
    """
    log_a = np.log(price_a.dropna())
    log_b = np.log(price_b.dropna())
    common = log_a.index.intersection(log_b.index)
    stat, pval, _ = coint(log_a.loc[common], log_b.loc[common])
    return float(stat), float(pval)


def johansen_test(
    price_a: pd.Series,
    price_b: pd.Series,
    det_order: int = 0,
    k_ar_diff: int = 1,
    significance: float = 0.05,
) -> tuple[bool, float | None]:
    """Johansen cointegration test on log prices.

    Tests H0: no cointegration using the trace statistic.  Supports 90%, 95%,
    and 99% significance levels (0.10, 0.05, 0.01).

    Parameters
    ----------
    det_order:
        Deterministic terms: -1 = no constant, 0 = constant, 1 = trend.
    k_ar_diff:
        Number of lagged differences in the VAR model.
    significance:
        Significance level for critical-value comparison (0.10 | 0.05 | 0.01).

    Returns
    -------
    (is_cointegrated, trace_statistic)
        trace_statistic is None if statsmodels is unavailable or test fails.
    """
    try:
        from statsmodels.tsa.vector_ar.vecm import coint_johansen  # noqa: PLC0415
    except ImportError:
        logger.warning("coint_johansen not available; falling back to Engle-Granger")
        _, pval = engle_granger_test(price_a, price_b)
        return pval < significance, None

    log_a = np.log(price_a.dropna())
    log_b = np.log(price_b.dropna())
    common = log_a.index.intersection(log_b.index)
    data = np.column_stack([log_a.loc[common].values, log_b.loc[common].values])

    try:
        result = coint_johansen(data, det_order=det_order, k_ar_diff=k_ar_diff)
    except Exception:
        logger.exception("Johansen test failed; falling back to Engle-Granger")
        _, pval = engle_granger_test(price_a, price_b)
        return pval < significance, None

    # Trace statistic for rank 0 (H0: no cointegrating vector)
    trace_stat = float(result.lr1[0])
    # Critical values: columns are [90%, 95%, 99%]
    sig_to_col = {0.10: 0, 0.05: 1, 0.01: 2}
    col = sig_to_col.get(significance, 1)
    crit = float(result.cvt[0, col])
    return trace_stat > crit, trace_stat


def kalman_spread(
    price_a: pd.Series,
    price_b: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Estimate a dynamic (time-varying) hedge ratio via a univariate Kalman filter.

    Models the relationship  log_A_t = beta_t * log_B_t + alpha_t  where beta
    is treated as a random walk state tracked by the Kalman filter.

    Parameters
    ----------
    price_a, price_b : price series aligned on the same index.

    Returns
    -------
    (spread_series, hedge_ratio_series)
        spread = log_A - hedge_ratio * log_B
        hedge_ratio is the filtered (posterior mean) beta at each bar.

    Notes
    -----
    Adapted from the Kalman-filter pairs-trading exposition in
    stefan-jansen/machine-learning-for-trading ch4
    (04_alpha_factor_research/03_kalman_filter_and_wavelets.ipynb).
    """
    log_a = np.log(price_a)
    log_b = np.log(price_b)
    common = log_a.index.intersection(log_b.index)
    log_a = log_a.loc[common].values
    log_b = log_b.loc[common].values
    n = len(log_a)

    # State: [beta, alpha].  Transition: random walk.
    # Observation: log_a = H @ state + noise
    # Process noise (Q) and observation noise (R) are fixed hyper-parameters.
    delta = 1e-4       # process noise variance (spread of beta random walk)
    Ve = 0.001         # observation noise variance

    # State covariance
    C = np.zeros((2, 2))
    x = np.zeros(2)    # [beta, alpha] initial guess
    Q = delta / (1 - delta) * np.eye(2)

    betas = np.empty(n)
    alphas = np.empty(n)

    for t in range(n):
        # Observation vector H = [log_b_t, 1]
        H = np.array([log_b[t], 1.0])

        # Predict
        # (state transition is identity for random walk)
        C = C + Q

        # Update
        innovation = log_a[t] - H @ x
        S = H @ C @ H + Ve          # innovation variance
        K = C @ H / S               # Kalman gain (2,)
        x = x + K * innovation
        C = (np.eye(2) - np.outer(K, H)) @ C

        betas[t] = x[0]
        alphas[t] = x[1]

    hedge_ratio_series = pd.Series(betas, index=common, name="kalman_beta")
    spread_series = pd.Series(
        log_a - betas * log_b,
        index=common,
        name="kalman_spread",
    )
    return spread_series, hedge_ratio_series


def half_life(spread: pd.Series) -> float:
    """Estimate the Ornstein-Uhlenbeck mean-reversion half-life of a spread.

    Fits the AR(1) regression:  Δspread_t = λ * spread_{t-1} + ε
    and returns  half_life = -log(2) / log(1 + λ) ≈ -log(2) / λ  (bars).

    A shorter half-life implies faster mean reversion.  Returns ``inf`` if
    the spread is not mean-reverting (λ ≥ 0).

    Adapted from stefan-jansen/machine-learning-for-trading ch9
    (05_cointegration_tests.ipynb).
    """
    spread = spread.dropna()
    if len(spread) < 20:
        return float("inf")
    delta = spread.diff().dropna()
    lagged = spread.shift(1).dropna()
    common = delta.index.intersection(lagged.index)
    y = delta.loc[common].values
    x = lagged.loc[common].values.reshape(-1, 1)
    x_const = np.column_stack([x, np.ones(len(x))])
    try:
        res = OLS(y, x_const).fit()
        lam = float(res.params[0])
        if lam >= 0:
            return float("inf")
        if 1 + lam <= 0:
            # Over-differenced or lam < -1: mathematically undefined, treat as very fast reversion
            return 1.0
        return float(-np.log(2) / np.log(1 + lam))
    except Exception:
        return float("inf")


def hedge_ratio(price_a: pd.Series, price_b: pd.Series) -> float:
    """Estimate OLS hedge ratio β such that price_A ≈ β * price_B + α.

    Uses log prices.
    """
    log_a = np.log(price_a.dropna())
    log_b = np.log(price_b.dropna())
    common = log_a.index.intersection(log_b.index)
    y = log_a.loc[common].values
    x = log_b.loc[common].values
    x_with_const = np.column_stack([x, np.ones_like(x)])
    result = OLS(y, x_with_const).fit()
    return float(result.params[0])


def compute_spread(
    price_a: pd.Series, price_b: pd.Series, beta: float
) -> pd.Series:
    """Compute spread S = log(A) - β * log(B)."""
    log_a = np.log(price_a)
    log_b = np.log(price_b)
    spread = log_a - beta * log_b
    spread.name = "spread"
    return spread


def zscore(spread: pd.Series, window: int) -> pd.Series:
    """Rolling z-score: (spread - rolling_mean) / rolling_std."""
    mu = spread.rolling(window=window, min_periods=window).mean()
    sigma = spread.rolling(window=window, min_periods=window).std()
    return (spread - mu) / sigma.replace(0, np.nan)


def is_cointegrated(
    price_a: pd.Series,
    price_b: pd.Series,
    pvalue_threshold: float = 0.05,
    method: str = "engle_granger",
) -> tuple[bool, float]:
    """Return (True, p_value_or_stat) if the pair is cointegrated.

    Parameters
    ----------
    method : 'engle_granger' | 'johansen'
        Which cointegration test to use.  'johansen' uses the trace statistic
        compared at the ``pvalue_threshold`` significance level (only 0.10,
        0.05, 0.01 are supported; defaults to 0.05).
    """
    if method == "johansen":
        is_coint, stat = johansen_test(price_a, price_b, significance=pvalue_threshold)
        return is_coint, stat if stat is not None else float("nan")
    _, pval = engle_granger_test(price_a, price_b)
    return pval < pvalue_threshold, pval

