"""Lean CLI subprocess wrapper."""
from __future__ import annotations
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("fxhe.lean.runner")


@dataclass
class BacktestResult:
    """Parsed result from a Lean backtest run."""
    algorithm: str
    total_return: float
    sharpe: float
    max_drawdown: float
    trades: int
    raw: dict


def run_backtest(
    project_dir: str | Path,
    config_path: str | Path | None = None,
    extra_args: list[str] | None = None,
    timeout: int = 600,
) -> BacktestResult:
    """Run 'lean backtest' for a project and parse the results JSON.

    Parameters
    ----------
    project_dir:
        Path to the Lean project directory containing the algorithm .py file.
    config_path:
        Optional path to a custom lean_config.yaml.
    extra_args:
        Additional CLI arguments passed to 'lean backtest'.
    timeout:
        Maximum seconds to wait for backtest completion.

    Returns
    -------
    BacktestResult parsed from the Lean output JSON.
    """
    cmd = ["lean", "backtest", str(project_dir)]
    if config_path:
        cmd += ["--config", str(config_path)]
    if extra_args:
        cmd += extra_args

    logger.info("Running Lean backtest: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if proc.returncode != 0:
        logger.error("Lean backtest failed:\n%s", proc.stderr)
        raise RuntimeError(f"Lean backtest failed with code {proc.returncode}:\n{proc.stderr}")

    # Lean writes results to backtests/<timestamp>/results.json by default
    project_path = Path(project_dir)
    results_files = sorted(project_path.glob("backtests/**/results.json"))
    if not results_files:
        raise FileNotFoundError("Could not find results.json in backtest output")

    with open(results_files[-1]) as f:
        raw = json.load(f)

    stats = raw.get("Statistics", {})
    return BacktestResult(
        algorithm=raw.get("AlgorithmId", "unknown"),
        total_return=_parse_pct(stats.get("Total Return", "0%")),
        sharpe=float(stats.get("Sharpe Ratio", 0)),
        max_drawdown=_parse_pct(stats.get("Drawdown", "0%")),
        trades=int(stats.get("Total Trades", 0)),
        raw=raw,
    )


def _parse_pct(value: str) -> float:
    return float(value.strip().rstrip("%")) / 100


def run_cloud_push(project_dir: str | Path) -> None:
    """Push a Lean project to QuantConnect cloud."""
    cmd = ["lean", "cloud", "push", "--project", str(project_dir)]
    logger.info("Pushing to QC cloud: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"Cloud push failed:\n{proc.stderr}")
    logger.info("Cloud push succeeded")
