"""Cointegration fit routines for Phase 2."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from fx_lean_engine.types import PairFitResult


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    design = np.column_stack([np.ones_like(x), x])
    coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
    return float(coeffs[0]), float(coeffs[1])


def _half_life(spread: np.ndarray) -> float:
    if spread.size < 3:
        return float("inf")
    lag = spread[:-1]
    delta = np.diff(spread)
    design = np.column_stack([np.ones_like(lag), lag])
    coeffs, *_ = np.linalg.lstsq(design, delta, rcond=None)
    phi = float(coeffs[1])
    if phi >= 0:
        return float("inf")
    return float(-np.log(2.0) / phi)


def _safe_coint_pvalue(y: np.ndarray, x: np.ndarray) -> float:
    try:
        from statsmodels.tsa.stattools import coint

        _, p_value, _ = coint(y, x)
        return float(min(max(p_value, 0.0), 1.0))
    except Exception:
        # Conservative fallback when statsmodels missing: treat as non-cointegrated.
        return 1.0


def fit_pair(y: np.ndarray, x: np.ndarray, lookback: int, pair: tuple[str, str], timestamp: datetime) -> PairFitResult:
    """Fit one pair and return cointegration/stability metrics."""
    lb = max(int(lookback), 30)
    if y.size != x.size:
        raise ValueError("fit_pair requires equal-length y and x")
    if y.size < lb:
        raise ValueError("fit_pair requires at least lookback samples")

    yw = np.asarray(y[-lb:], dtype=float)
    xw = np.asarray(x[-lb:], dtype=float)

    intercept, beta = _ols(yw, xw)
    spread = yw - (intercept + beta * xw)
    spread_std = float(np.std(spread, ddof=1)) if spread.size > 1 else 0.0
    spread_last_z = 0.0 if spread_std <= 1e-12 else float((spread[-1] - np.mean(spread)) / spread_std)
    half_life = _half_life(spread)
    p_value = _safe_coint_pvalue(yw, xw)

    half = max(lb // 2, 15)
    _, beta_a = _ols(yw[:half], xw[:half])
    _, beta_b = _ols(yw[-half:], xw[-half:])
    beta_drift = float(abs(beta_b - beta_a))

    return PairFitResult(
        pair=pair,
        beta=float(beta),
        intercept=float(intercept),
        p_value=float(p_value),
        spread_std=float(spread_std),
        half_life=float(half_life),
        beta_drift=float(beta_drift),
        spread_last_z=float(spread_last_z),
        timestamp=timestamp,
    )
