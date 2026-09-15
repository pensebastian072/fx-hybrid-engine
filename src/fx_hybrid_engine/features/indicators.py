"""Technical indicator computations."""
from __future__ import annotations
import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (0–100)."""
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=window, min_periods=window).mean()
    loss = (-delta.clip(upper=0)).rolling(window=window, min_periods=window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def rolling_vol(series: pd.Series, window: int = 20, annualize: bool = True) -> pd.Series:
    """Rolling realized volatility (std of log returns).

    Parameters
    ----------
    annualize:
        If True, multiply by sqrt(252) to get annualized vol.
    """
    log_ret = np.log(series / series.shift(1))
    vol = log_ret.rolling(window=window, min_periods=window).std()
    if annualize:
        vol = vol * np.sqrt(252)
    return vol


def momentum_slope(series: pd.Series, window: int = 20) -> pd.Series:
    """Estimate trend slope via OLS over a rolling window.

    Returns the slope coefficient normalized by the current price level.
    """
    slopes = pd.Series(index=series.index, dtype=float)
    x = np.arange(window, dtype=float)
    x -= x.mean()  # center for numerical stability
    for i in range(window - 1, len(series)):
        y = series.iloc[i - window + 1 : i + 1].values.astype(float)
        if np.any(np.isnan(y)) or y[-1] == 0:
            continue
        slope = float(np.dot(x, y - y.mean()) / np.dot(x, x))
        slopes.iloc[i] = slope / y[-1]  # normalize by current price
    return slopes


def compute_all(
    close: pd.Series,
    sma_fast: int = 50,
    sma_slow: int = 200,
    rsi_window: int = 14,
    vol_window: int = 20,
    mom_window: int = 20,
) -> pd.DataFrame:
    """Compute all standard indicators and return as a DataFrame."""
    return pd.DataFrame(
        {
            "close": close,
            "log_return": np.log(close / close.shift(1)),
            "sma_fast": sma(close, sma_fast),
            "sma_slow": sma(close, sma_slow),
            "ema_fast": ema(close, sma_fast),
            "rsi": rsi(close, rsi_window),
            "realized_vol": rolling_vol(close, vol_window),
            "momentum_slope": momentum_slope(close, mom_window),
            "sma_crossover": (sma(close, sma_fast) - sma(close, sma_slow)) / close,
        }
    )
