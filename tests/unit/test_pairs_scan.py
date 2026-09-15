"""Unit tests for rolling pair scan diagnostics."""
from __future__ import annotations

import numpy as np
import pandas as pd

from fx_hybrid_engine.engines.pairs_scan import build_pairs_diagnostics, scan_candidate_pairs


def _cointegrated_data(n: int = 240) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(123)
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    common = np.cumsum(rng.normal(0.0, 0.001, n))
    a = np.exp(5.0 + common)
    b = np.exp(5.0 + (common / 1.2) + np.cumsum(rng.normal(0.0, 0.0002, n)))
    return {
        "A": pd.DataFrame({"close": a}, index=idx),
        "B": pd.DataFrame({"close": b}, index=idx),
    }


def test_scan_candidate_pairs_emits_expected_columns():
    data = _cointegrated_data()
    out = scan_candidate_pairs(
        data,
        [["A", "B"]],
        cointegration_threshold=0.2,
        spread_window=40,
        entry_zscore=2.0,
        min_train_bars=80,
        scan_frequency_bars=40,
    )
    assert not out.candidates.empty
    assert not out.scans.empty
    assert {"pair_id", "pvalue", "beta", "spread_std", "z_abs_p95", "scan_idx"} <= set(out.scans.columns)


def test_build_pairs_diagnostics_reason_mapping():
    scans = pd.DataFrame(
        [
            {"pair_id": "A-B", "reason": "ok", "pvalue": 0.40, "beta": 1.0, "spread_std": 0.2, "z_abs_p95": 0.8},
            {"pair_id": "A-B", "reason": "ok", "pvalue": 0.35, "beta": 1.1, "spread_std": 0.2, "z_abs_p95": 0.9},
        ]
    )
    diag = build_pairs_diagnostics(
        scans,
        pair_ids=["A-B"],
        cointegration_threshold=0.05,
        entry_zscore=2.0,
        state_map={"A-B": "WATCH"},
        trade_counts={"A-B": 0},
    )
    assert len(diag) == 1
    assert diag.iloc[0]["primary_reason"] == "pvalue_fail"
