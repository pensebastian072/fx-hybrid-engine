"""Extended performance metrics for strategy evaluation.

Supplements the existing walk-forward evaluation infrastructure with additional
risk-adjusted return measures used throughout ML-for-trading literature.

Metrics adapted from:
- stefan-jansen/machine-learning-for-trading ch5
  (05_strategy_evaluation notebooks: Sharpe, Sortino, Calmar, Omega, IR)
- Standard quant finance references (Bacon 2008, Lo 2002)

All functions accept a ``pd.Series`` of arithmetic equity-curve values
(i.e., cumulative portfolio value starting at 1.0) or a returns series,
and return scalar floats (or dicts for multi-metric helpers).

Functions are pure/stateless — no side effects.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _to_returns(equity_or_returns: pd.Series) -> pd.Series:
    """Convert equity curve to period returns if not already returns."""
    s = equity_or_returns.dropna()
    if len(s) < 2:
        return pd.Series(dtype=float)
    if s.iloc[0] > 10:
        # Looks like an equity curve (values far from 0); compute log returns
        return np.log(s / s.shift(1)).dropna()
    # Assume already returns-like (small values around 0)
    return s


def max_drawdown(equity: pd.Series) -> float:
    """Maximum peak-to-trough drawdown (as a positive fraction, e.g. 0.15 = 15%).

    Parameters
    ----------
    equity:
        Cumulative wealth index (values > 0, e.g. starting at 100 or 1.0).
        Do NOT pass a returns series — use ``(1 + returns).cumprod()`` first.
    """
    eq = equity.dropna()
    if len(eq) < 2:
        return 0.0
    peak = eq.cummax()
    dd = (eq - peak) / peak
    return float(-dd.min())


def max_drawdown_duration(equity: pd.Series) -> int:
    """Maximum drawdown duration in bars (time from peak to recovery or end).

    Parameters
    ----------
    equity:
        Cumulative wealth index (values > 0). Do NOT pass returns.

    Returns
    -------
    int: longest number of consecutive bars spent in drawdown.
    """
    eq = equity.dropna()
    if len(eq) < 2:
        return 0
    peak = eq.cummax()
    in_dd = (eq < peak).astype(int)
    durations: list[int] = []
    current = 0
    for v in in_dd:
        if v:
            current += 1
        else:
            if current:
                durations.append(current)
            current = 0
    if current:
        durations.append(current)
    return max(durations) if durations else 0


# ---------------------------------------------------------------------------
# Risk-adjusted return metrics
# ---------------------------------------------------------------------------


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio (assumes zero risk-free rate)."""
    r = _to_returns(returns).dropna()
    if r.std() == 0 or len(r) < 2:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, periods_per_year: int = 252, target: float = 0.0) -> float:
    """Annualized Sortino ratio using downside deviation.

    Parameters
    ----------
    target : float
        Minimum acceptable return per period (typically 0.0).
    """
    r = _to_returns(returns).dropna()
    if len(r) < 2:
        return 0.0
    excess = r - target
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf")
    downside_std = np.sqrt((downside**2).mean())
    if downside_std == 0:
        return float("inf")
    return float(excess.mean() / downside_std * np.sqrt(periods_per_year))


def calmar_ratio(equity: pd.Series, periods_per_year: int = 252) -> float:
    """Calmar ratio: annualized return / max drawdown.

    Parameters
    ----------
    equity:
        Cumulative wealth index (values > 0). Returns 0.0 if max drawdown is zero.
    """
    r = _to_returns(equity).dropna()
    if len(r) < 2:
        return 0.0
    ann_return = float(r.mean() * periods_per_year)
    mdd = max_drawdown(equity)
    if mdd == 0:
        return 0.0
    return ann_return / mdd


def omega_ratio(returns: pd.Series, threshold: float = 0.0) -> float:
    """Omega ratio: probability-weighted ratio of gains to losses above threshold.

    A value > 1 indicates more gain-probability than loss-probability.
    """
    r = _to_returns(returns).dropna()
    if len(r) == 0:
        return 1.0
    gains = r[r > threshold] - threshold
    losses = threshold - r[r <= threshold]
    sum_losses = losses.sum()
    if sum_losses == 0:
        return float("inf")
    return float(gains.sum() / sum_losses)


def information_ratio(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: int = 252,
) -> float:
    """Information ratio: annualized active return / tracking error.

    Parameters
    ----------
    strategy_returns, benchmark_returns:
        Period returns for the strategy and benchmark respectively.
        Must be aligned on the same index.
    """
    common = strategy_returns.index.intersection(benchmark_returns.index)
    active = strategy_returns.loc[common] - benchmark_returns.loc[common]
    active = active.dropna()
    if len(active) < 2 or active.std() == 0:
        return 0.0
    return float(active.mean() / active.std() * np.sqrt(periods_per_year))


# ---------------------------------------------------------------------------
# Win/loss streak analytics
# ---------------------------------------------------------------------------


def _streaks(returns: pd.Series) -> tuple[int, int]:
    """Return (max_winning_streak, max_losing_streak) in bars."""
    r = _to_returns(returns).dropna()
    if len(r) == 0:
        return 0, 0
    signs = (r > 0).astype(int) * 2 - 1  # +1 win, -1 loss
    max_win = max_lose = cur_win = cur_lose = 0
    for s in signs:
        if s > 0:
            cur_win += 1
            cur_lose = 0
        else:
            cur_lose += 1
            cur_win = 0
        max_win = max(max_win, cur_win)
        max_lose = max(max_lose, cur_lose)
    return max_win, max_lose


def avg_trade_return(returns: pd.Series) -> tuple[float, float]:
    """Return (avg_winner_return, avg_loser_return) from a returns series."""
    r = _to_returns(returns).dropna()
    winners = r[r > 0]
    losers = r[r <= 0]
    avg_win = float(winners.mean()) if len(winners) else 0.0
    avg_lose = float(losers.mean()) if len(losers) else 0.0
    return avg_win, avg_lose


# ---------------------------------------------------------------------------
# Composite metric builder
# ---------------------------------------------------------------------------


def compute_extended_metrics(
    equity: pd.Series,
    benchmark_returns: pd.Series | None = None,
    periods_per_year: int = 252,
) -> dict[str, float]:
    """Compute the full suite of extended performance metrics.

    Parameters
    ----------
    equity:
        Cumulative wealth index (values > 0, e.g. starting at 1.0 or 100.0).
        Pass ``(1 + returns).cumprod()`` if you have a returns series.
    benchmark_returns:
        Optional benchmark returns series for Information Ratio.
    periods_per_year:
        Trading periods per year for annualization.

    Returns
    -------
    dict with keys:
        sharpe, sortino, calmar, omega, information_ratio,
        max_drawdown, max_drawdown_duration_bars,
        avg_winner_pct, avg_loser_pct,
        max_winning_streak, max_losing_streak
    """
    r = _to_returns(equity)
    max_win_streak, max_lose_streak = _streaks(r)
    avg_win, avg_lose = avg_trade_return(r)

    ir = 0.0
    if benchmark_returns is not None:
        ir = information_ratio(r, benchmark_returns, periods_per_year)

    return {
        "sharpe": sharpe_ratio(r, periods_per_year),
        "sortino": sortino_ratio(r, periods_per_year),
        "calmar": calmar_ratio(equity, periods_per_year),
        "omega": omega_ratio(r),
        "information_ratio": ir,
        "max_drawdown": max_drawdown(equity),
        "max_drawdown_duration_bars": float(max_drawdown_duration(equity)),
        "avg_winner_pct": avg_win * 100,
        "avg_loser_pct": avg_lose * 100,
        "max_winning_streak": float(max_win_streak),
        "max_losing_streak": float(max_lose_streak),
    }
