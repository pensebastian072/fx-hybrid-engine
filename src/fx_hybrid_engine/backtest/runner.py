"""Backtest runner: parameter sweep over config variants."""
from __future__ import annotations
import copy
import logging
from pathlib import Path
import pandas as pd
import yaml

from fx_hybrid_engine.lean.lean_runner import BacktestResult, run_backtest
from fx_hybrid_engine.utils.config import load_config

logger = logging.getLogger("fxhe.backtest.runner")


def sweep(
    base_config_path: str | Path,
    param_grid: dict[str, list],
    project_dir: str | Path,
    output_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Run backtests over a grid of parameter overrides.

    Parameters
    ----------
    base_config_path:
        Path to base default.yaml.
    param_grid:
        Dict of dotted config key → list of values.
        Example: {"pairs_engine.entry_zscore": [1.5, 2.0, 2.5]}
    project_dir:
        Lean project directory.
    output_csv:
        Optional path to save results CSV.

    Returns
    -------
    DataFrame with one row per parameter combination.
    """
    import itertools  # noqa: PLC0415

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    records = []

    for combo in itertools.product(*values):
        params = dict(zip(keys, combo))
        cfg_path = _write_temp_config(base_config_path, params)
        try:
            result = run_backtest(project_dir, config_path=cfg_path)
            row = {**params, "total_return": result.total_return, "sharpe": result.sharpe, "max_drawdown": result.max_drawdown, "trades": result.trades}
            records.append(row)
            logger.info("Params %s → Sharpe %.3f", params, result.sharpe)
        except Exception:
            logger.exception("Backtest failed for params %s", params)
            records.append({**params, "total_return": float("nan"), "sharpe": float("nan"), "max_drawdown": float("nan"), "trades": 0})
        finally:
            cfg_path.unlink(missing_ok=True)

    df = pd.DataFrame(records)
    if output_csv:
        df.to_csv(output_csv, index=False)
        logger.info("Sweep results saved to %s", output_csv)
    return df


def _write_temp_config(base_path: Path | str, overrides: dict[str, object]) -> Path:
    """Write a modified YAML config with dot-notation overrides."""
    with open(base_path) as f:
        cfg: dict = yaml.safe_load(f)

    for dotted_key, value in overrides.items():
        parts = dotted_key.split(".")
        node = cfg
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    tmp_path = Path(base_path).parent / "_sweep_tmp.yaml"
    with open(tmp_path, "w") as f:
        yaml.dump(cfg, f)
    return tmp_path
