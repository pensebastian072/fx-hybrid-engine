"""Robustness sweeps for costs and parameter perturbations."""
from __future__ import annotations

import copy
from collections.abc import Callable

import numpy as np
import pandas as pd

from fx_hybrid_engine.reporting.metrics import max_drawdown, sharpe_ratio, win_rate
from fx_hybrid_engine.utils.config import EngineConfig, ExecutionCostsConfig, RobustnessConfig


def _metrics_from_net_returns(net_returns: pd.Series, equity: pd.Series) -> dict[str, float]:
    return {
        "total_return": float(equity.iloc[-1] - 1.0) if len(equity) else 0.0,
        "sharpe": sharpe_ratio(net_returns) if len(net_returns) else 0.0,
        "max_drawdown": max_drawdown(equity) if len(equity) else 0.0,
        "win_rate": win_rate(net_returns) if len(net_returns) else 0.0,
    }


def recompute_equity_with_costs(
    equity_curve: pd.DataFrame,
    costs: ExecutionCostsConfig,
) -> dict[str, float]:
    """Recompute metrics from stored gross returns + turnover under alternate costs."""
    if equity_curve.empty:
        return {"total_return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0}

    equity = 1.0
    net_rets: list[float] = []
    total_bps = float(costs.commission_bps + costs.slippage_bps) / 10_000.0
    for _, row in equity_curve.iterrows():
        prev = equity
        gross_ret = float(row.get("gross_return", 0.0))
        turnover = float(row.get("turnover", 0.0))
        equity *= 1.0 + gross_ret
        equity -= equity * turnover * total_bps
        net_rets.append((equity / prev) - 1.0 if prev else 0.0)
    eq = pd.Series(np.cumprod([1.0 + r for r in net_rets]))
    nr = pd.Series(net_rets)
    return _metrics_from_net_returns(nr, eq)


def run_cost_sweep(
    hybrid_equity_by_split: dict[int, pd.DataFrame],
    base_costs: ExecutionCostsConfig,
    robustness: RobustnessConfig,
) -> pd.DataFrame:
    """Run configured cost/slippage scenarios and return split-level metrics."""
    rows: list[dict[str, object]] = []
    for scenario in robustness.cost_scenarios:
        name = str(scenario.get("name", "unnamed"))
        comm_mult = float(scenario.get("commission_mult", 1.0))
        slip_mult = float(scenario.get("slippage_mult", 1.0))
        costs = ExecutionCostsConfig(
            commission_bps=base_costs.commission_bps * comm_mult,
            slippage_bps=base_costs.slippage_bps * slip_mult,
        )
        for split_idx, equity_df in hybrid_equity_by_split.items():
            m = recompute_equity_with_costs(equity_df, costs)
            rows.append(
                {
                    "scenario": name,
                    "split_idx": split_idx,
                    "commission_bps": costs.commission_bps,
                    "slippage_bps": costs.slippage_bps,
                    **m,
                }
            )
    return pd.DataFrame(rows)


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def jitter_config(base_cfg: EngineConfig, rng: np.random.Generator) -> EngineConfig:
    """Create one perturbed config sample from the base config."""
    cfg = copy.deepcopy(base_cfg)
    rob = cfg.robustness

    z_jitter = 1.0 + rng.uniform(-rob.pairs_zscore_jitter_pct, rob.pairs_zscore_jitter_pct)
    coint_jitter = 1.0 + rng.uniform(-rob.cointegration_jitter_pct, rob.cointegration_jitter_pct)
    risk_jitter = 1.0 + rng.uniform(-rob.risk_cap_jitter_pct, rob.risk_cap_jitter_pct)
    trend_jitter = rng.uniform(-rob.trend_threshold_jitter_abs, rob.trend_threshold_jitter_abs)

    cfg.pairs.entry_zscore = _clip(cfg.pairs.entry_zscore * z_jitter, 0.5, 5.0)
    cfg.pairs.exit_zscore = _clip(cfg.pairs.exit_zscore * z_jitter, 0.1, cfg.pairs.entry_zscore)
    cfg.pairs.cointegration_pvalue_threshold = _clip(cfg.pairs.cointegration_pvalue_threshold * coint_jitter, 0.001, 0.5)
    cfg.trend.signal_threshold = _clip(cfg.trend.signal_threshold + trend_jitter, 0.5, 0.95)
    cfg.risk.max_leverage = _clip(cfg.risk.max_leverage * risk_jitter, 0.5, 5.0)
    cfg.risk.drawdown_kill_pct = _clip(cfg.risk.drawdown_kill_pct * risk_jitter, 0.01, 0.5)
    return cfg


def run_parameter_sweep(
    base_cfg: EngineConfig,
    evaluate_fn: Callable[[EngineConfig], dict[str, float]],
) -> pd.DataFrame:
    """Run seeded perturbation samples using evaluate_fn for each sample."""
    rng = np.random.default_rng(base_cfg.robustness.random_seed)
    rows: list[dict[str, object]] = []
    for sample_idx in range(base_cfg.robustness.param_sweep_samples):
        cfg = jitter_config(base_cfg, rng)
        metrics = evaluate_fn(cfg)
        rows.append(
            {
                "sample_idx": sample_idx,
                "entry_zscore": cfg.pairs.entry_zscore,
                "exit_zscore": cfg.pairs.exit_zscore,
                "cointegration_pvalue_threshold": cfg.pairs.cointegration_pvalue_threshold,
                "trend_signal_threshold": cfg.trend.signal_threshold,
                "max_leverage": cfg.risk.max_leverage,
                "drawdown_kill_pct": cfg.risk.drawdown_kill_pct,
                **metrics,
            }
        )
    return pd.DataFrame(rows)


def robustness_diagnostics(param_sweep_df: pd.DataFrame, base_median_return: float) -> dict[str, float]:
    if param_sweep_df.empty:
        return {
            "positive_return_share": 0.0,
            "non_negative_sharpe_share": 0.0,
            "relative_return_degradation": 1.0,
        }
    pos_share = float((param_sweep_df["median_total_return"] > 0).mean())
    sharpe_share = float((param_sweep_df["median_sharpe"] >= 0).mean())
    med = float(param_sweep_df["median_total_return"].median())
    rel_deg = float((base_median_return - med) / abs(base_median_return)) if base_median_return != 0 else 0.0
    return {
        "positive_return_share": pos_share,
        "non_negative_sharpe_share": sharpe_share,
        "relative_return_degradation": rel_deg,
    }

