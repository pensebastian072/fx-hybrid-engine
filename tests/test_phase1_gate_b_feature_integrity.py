"""Phase 1 Gate B tests: feature integrity."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from fx_lean_engine.backtest.synthetic import run_synthetic_backtest


def test_phase1_gate_b_feature_rows_are_finite(tmp_path: Path) -> None:
    out_dir = run_synthetic_backtest(tmp_path / "phase1_gate_b")

    features = pd.read_csv(out_dir / "features.csv")
    assert not features.empty

    numeric = features.select_dtypes(include=[np.number])
    assert not numeric.isna().any().any()
    assert not np.isinf(numeric.to_numpy(dtype=float)).any()

    metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    counters = metrics["feature_counters"]
    assert counters["feature_updates_emitted"] > 0
    assert counters["feature_updates_nan_rejected"] == 0
