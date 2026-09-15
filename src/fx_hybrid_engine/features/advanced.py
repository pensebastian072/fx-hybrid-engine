"""Advanced technical indicators for ML-based signal generation.

Adapted from concepts in:
- stefan-jansen/machine-learning-for-trading (ch4, ch9)
- cwu392/Machine-Learning-for-Trading (strategy learner/indicators.py)

All functions accept pandas Series/DataFrame inputs and return pandas Series
or DataFrames aligned to the same index.  Functions return NaN for the warmup
period so callers can safely dropna().
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


def bollinger_bands(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    """Bollinger Bands: middle, upper, lower bands plus %B and bandwidth.

    Returns
    -------
    DataFrame with columns: bb_mid, bb_upper, bb_lower, bb_pct_b, bb_bandwidth
    """
    mid = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    band_width = (upper - lower) / mid.replace(0, np.nan)
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame(
        {
            "bb_mid": mid,
            "bb_upper": upper,
            "bb_lower": lower,
            "bb_pct_b": pct_b,
            "bb_bandwidth": band_width,
        },
        index=close.index,
    )


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_window: int = 9,
) -> pd.DataFrame:
    """Moving Average Convergence/Divergence.

    Returns
    -------
    DataFrame with columns: macd_line, macd_signal, macd_histogram
    """
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    macd_sig = macd_line.ewm(span=signal_window, adjust=False, min_periods=signal_window).mean()
    macd_hist = macd_line - macd_sig
    return pd.DataFrame(
        {
            "macd_line": macd_line,
            "macd_signal": macd_sig,
            "macd_histogram": macd_hist,
        },
        index=close.index,
    )


# ---------------------------------------------------------------------------
# Average True Range (ATR)
# ---------------------------------------------------------------------------


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average True Range — a measure of volatility.

    Returns a Series named 'atr'.
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    result = tr.rolling(window=window, min_periods=window).mean()
    result.name = "atr"
    return result


# ---------------------------------------------------------------------------
# Stochastic Oscillator
# ---------------------------------------------------------------------------


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_window: int = 14,
    d_window: int = 3,
) -> pd.DataFrame:
    """Stochastic Oscillator %K and smoothed %D.

    Returns
    -------
    DataFrame with columns: stoch_k, stoch_d
    """
    lowest_low = low.rolling(window=k_window, min_periods=k_window).min()
    highest_high = high.rolling(window=k_window, min_periods=k_window).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = k.rolling(window=d_window, min_periods=d_window).mean()
    return pd.DataFrame({"stoch_k": k, "stoch_d": d}, index=close.index)


# ---------------------------------------------------------------------------
# Williams %R
# ---------------------------------------------------------------------------


def williams_r(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
) -> pd.Series:
    """Williams %R oscillator (range –100 to 0; overbought > –20, oversold < –80).

    Returns a Series named 'williams_r'.
    """
    highest_high = high.rolling(window=window, min_periods=window).max()
    lowest_low = low.rolling(window=window, min_periods=window).min()
    result = -100 * (highest_high - close) / (highest_high - lowest_low).replace(0, np.nan)
    result.name = "williams_r"
    return result


# ---------------------------------------------------------------------------
# Commodity Channel Index (CCI)
# ---------------------------------------------------------------------------


def cci(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 20,
    constant: float = 0.015,
) -> pd.Series:
    """Commodity Channel Index.

    Returns a Series named 'cci'.
    """
    typical = (high + low + close) / 3.0
    rolling_mean = typical.rolling(window=window, min_periods=window).mean()
    rolling_mad = typical.rolling(window=window, min_periods=window).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    result = (typical - rolling_mean) / (constant * rolling_mad.replace(0, np.nan))
    result.name = "cci"
    return result


# ---------------------------------------------------------------------------
# On-Balance Volume (OBV)
# ---------------------------------------------------------------------------


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume — cumulative volume pressure indicator.

    Returns a Series named 'obv'.
    """
    direction = np.sign(close.diff()).fillna(0)
    result = (direction * volume).cumsum()
    result.name = "obv"
    return result


# ---------------------------------------------------------------------------
# Money Flow Index (MFI)
# ---------------------------------------------------------------------------


def mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    window: int = 14,
) -> pd.Series:
    """Money Flow Index — volume-weighted RSI variant (0–100).

    Returns a Series named 'mfi'.
    """
    typical = (high + low + close) / 3.0
    raw_money_flow = typical * volume
    flow_sign = np.sign(typical.diff()).fillna(0)
    pos_flow = raw_money_flow.where(flow_sign > 0, 0.0)
    neg_flow = raw_money_flow.where(flow_sign < 0, 0.0)
    pos_sum = pos_flow.rolling(window=window, min_periods=window).sum()
    neg_sum = neg_flow.abs().rolling(window=window, min_periods=window).sum()
    mfr = pos_sum / neg_sum.replace(0, np.nan)
    result = 100 - (100 / (1 + mfr))
    result.name = "mfi"
    return result


# ---------------------------------------------------------------------------
# Composite builder
# ---------------------------------------------------------------------------


def compute_all_advanced(
    close: pd.Series,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    volume: pd.Series | None = None,
    bb_window: int = 20,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    atr_window: int = 14,
    stoch_k: int = 14,
    stoch_d: int = 3,
    williams_window: int = 14,
    cci_window: int = 20,
    obv_enabled: bool = True,
    mfi_window: int = 14,
) -> pd.DataFrame:
    """Compute all advanced indicators and return as a single DataFrame.

    Parameters
    ----------
    close, high, low:
        OHLC price series (high/low optional; ATR, Stochastic, Williams %R, CCI
        will be omitted if not supplied).
    volume:
        Volume series (optional; OBV and MFI omitted if not supplied).

    Returns
    -------
    DataFrame aligned to ``close.index``.
    """
    parts: list[pd.DataFrame | pd.Series] = []

    # Bollinger Bands (close only)
    parts.append(bollinger_bands(close, window=bb_window))

    # MACD (close only)
    parts.append(macd(close, fast=macd_fast, slow=macd_slow, signal_window=macd_signal))

    if high is not None and low is not None:
        parts.append(atr(high, low, close, window=atr_window))
        parts.append(stochastic(high, low, close, k_window=stoch_k, d_window=stoch_d))
        parts.append(williams_r(high, low, close, window=williams_window))
        parts.append(cci(high, low, close, window=cci_window))

    if volume is not None:
        if obv_enabled:
            parts.append(obv(close, volume))
        if high is not None and low is not None:
            parts.append(mfi(high, low, close, volume, window=mfi_window))

    return pd.concat(parts, axis=1)
