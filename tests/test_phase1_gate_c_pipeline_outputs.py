"""Phase 1 Gate C tests: end-to-end pipeline artifacts."""

from __future__ import annotations

import pandas as pd
from pathlib import Path

from fx_lean_engine.backtest.synthetic import run_synthetic_backtest


def test_phase1_gate_c_pipeline_outputs(tmp_path: Path) -> None:
    out_dir = run_synthetic_backtest(tmp_path / "phase1_gate_c")

    signals = pd.read_csv(out_dir / "signals.csv")
    orders = pd.read_csv(out_dir / "orders.csv")
    regime = pd.read_csv(out_dir / "regime.csv")
    targets = pd.read_csv(out_dir / "targets.csv")
    equity = pd.read_csv(out_dir / "equity_curve.csv")

    assert not signals.empty
    assert not orders.empty
    assert not regime.empty
    assert not targets.empty
    assert not equity.empty

    assert {"pairs", "trend"}.issubset(set(signals["engine"].astype(str).str.lower().unique()))
    assert regime["state"].astype(str).str.len().gt(0).all()
    assert targets["target_notional_pct_nav"].abs().max() >= 0.0
