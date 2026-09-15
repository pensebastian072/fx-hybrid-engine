"""Performance metrics and per-regime PnL attribution."""
from __future__ import annotations
import numpy as np
import pandas as pd


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio (assumes zero risk-free rate)."""
    if returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def max_drawdown(equity_curve: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a positive fraction."""
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    return float(abs(drawdown.min()))


def win_rate(returns: pd.Series) -> float:
    """Fraction of positive return observations."""
    if len(returns) == 0:
        return 0.0
    return float((returns > 0).mean())


def regime_attribution(
    returns: pd.Series,
    regimes: pd.Series,
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """Compute per-regime performance metrics.

    Parameters
    ----------
    returns:
        Daily/bar returns of the strategy.
    regimes:
        Series of regime labels (same index as returns).
    periods_per_year:
        Bars per year for annualization.

    Returns
    -------
    DataFrame with columns [regime, n_bars, total_return, sharpe, max_dd, win_rate].
    """
    aligned = pd.DataFrame({"return": returns, "regime": regimes}).dropna()
    records = []
    for regime, group in aligned.groupby("regime"):
        r = group["return"]
        records.append({
            "regime": regime,
            "n_bars": len(r),
            "total_return": float((1 + r).prod() - 1),
            "sharpe": sharpe_ratio(r, periods_per_year),
            "max_drawdown": max_drawdown((1 + r).cumprod()),
            "win_rate": win_rate(r),
        })
    return pd.DataFrame(records).set_index("regime") if records else pd.DataFrame()


def engine_attribution(
    trades: pd.DataFrame,
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """Compute per-engine Sharpe, total return, win_rate.

    Parameters
    ----------
    trades:
        DataFrame with columns [engine, pnl] (one row per closed trade).
    """
    if trades.empty:
        return pd.DataFrame()
    records = []
    for engine, group in trades.groupby("engine"):
        r = group["pnl"]
        records.append({
            "engine": engine,
            "n_trades": len(r),
            "total_pnl": float(r.sum()),
            "sharpe": sharpe_ratio(r, periods_per_year),
            "win_rate": win_rate(r),
        })
    return pd.DataFrame(records).set_index("engine")
