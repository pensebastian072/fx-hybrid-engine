"""Unit tests for pair breakdown disable and cooldown behavior."""
from __future__ import annotations

import pandas as pd

from fx_hybrid_engine.engines.pair_validity import PairValidityManager


def test_breakdown_disable_and_recover():
    mgr = PairValidityManager(
        p_enter=0.08,
        p_exit=0.15,
        p_break=0.20,
        p_recover=0.10,
        break_scans_required=2,
        spread_std_spike_k=10.0,
        beta_jump_abs=10.0,
        cooldown_scans=2,
        entry_zscore=2.0,
    )
    scans = pd.DataFrame(
        [
            {"timestamp": "2024-01-01T00:00:00Z", "scan_idx": 0, "pair_id": "A-B", "pvalue": 0.30, "beta": 1.0, "spread_std": 0.2, "z_abs_p95": 2.5, "reason": "ok"},
            {"timestamp": "2024-01-01T00:15:00Z", "scan_idx": 1, "pair_id": "A-B", "pvalue": 0.32, "beta": 1.0, "spread_std": 0.2, "z_abs_p95": 2.5, "reason": "ok"},
            {"timestamp": "2024-01-01T00:30:00Z", "scan_idx": 2, "pair_id": "A-B", "pvalue": 0.05, "beta": 1.0, "spread_std": 0.2, "z_abs_p95": 2.5, "reason": "ok"},
            {"timestamp": "2024-01-01T00:45:00Z", "scan_idx": 3, "pair_id": "A-B", "pvalue": 0.05, "beta": 1.0, "spread_std": 0.2, "z_abs_p95": 2.5, "reason": "ok"},
            {"timestamp": "2024-01-01T01:00:00Z", "scan_idx": 4, "pair_id": "A-B", "pvalue": 0.05, "beta": 1.0, "spread_std": 0.2, "z_abs_p95": 2.5, "reason": "ok"},
        ]
    )
    for idx in sorted(scans["scan_idx"].unique()):
        mgr.apply_scan(scans.loc[scans["scan_idx"] == idx])

    assert mgr.state_for_pair("A-B") == "TRADABLE"
    events = mgr.events_df()
    assert "pvalue_breakdown" in set(events["reason"].astype(str))
    assert "cooldown_expired" in set(events["reason"].astype(str))
