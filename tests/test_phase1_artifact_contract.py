"""Phase 1 artifact contract tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fx_lean_engine.backtest.synthetic import run_synthetic_backtest
from fx_lean_engine.backtest.validation import validate_backtest_artifacts


def test_phase1_artifact_contract_required_files_present(tmp_path: Path) -> None:
    out_dir = run_synthetic_backtest(tmp_path / "phase1_contract")

    required = {
        "signals.csv",
        "orders.csv",
        "equity_curve.csv",
        "regime.csv",
        "features.csv",
        "targets.csv",
        "metrics.json",
        "run_manifest.json",
        "config_snapshot.yaml",
    }
    present = {path.name for path in out_dir.iterdir()}
    assert required.issubset(present)

    ok, issues = validate_backtest_artifacts(out_dir)
    assert ok is True, str(issues)


def test_phase1_artifact_contract_rejects_nan_features(tmp_path: Path) -> None:
    out_dir = run_synthetic_backtest(tmp_path / "phase1_contract_nan")
    features = pd.read_csv(out_dir / "features.csv")
    features.loc[0, "ret_1"] = float("nan")
    features.to_csv(out_dir / "features.csv", index=False)

    ok, issues = validate_backtest_artifacts(out_dir)
    assert ok is False
    assert any("contains NaN" in issue for issue in issues)
