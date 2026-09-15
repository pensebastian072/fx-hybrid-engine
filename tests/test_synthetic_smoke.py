"""Synthetic integration smoke test."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fx_lean_engine.backtest.synthetic import run_synthetic_backtest
from fx_lean_engine.backtest.validation import validate_backtest_artifacts


def test_synthetic_smoke_pipeline_end_to_end(tmp_path: Path) -> None:
    out_dir = run_synthetic_backtest(tmp_path / "synthetic")

    ok, issues = validate_backtest_artifacts(out_dir)
    assert ok is True, str(issues)

    signals = pd.read_csv(out_dir / "signals.csv")
    orders = pd.read_csv(out_dir / "orders.csv")
    equity = pd.read_csv(out_dir / "equity_curve.csv")

    assert not signals.empty
    assert not orders.empty
    assert not equity.empty
