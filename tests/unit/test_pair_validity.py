"""Unit tests for pair validity state machine hysteresis."""
from __future__ import annotations

import pandas as pd

from fx_hybrid_engine.engines.pair_validity import PairValidityManager


def _manager() -> PairValidityManager:
    return PairValidityManager(
        p_enter=0.08,
        p_exit=0.15,
        p_break=0.25,
        p_recover=0.10,
        break_scans_required=2,
        spread_std_spike_k=2.5,
        beta_jump_abs=0.3,
        cooldown_scans=2,
        entry_zscore=2.0,
    )


def test_hysteresis_watch_tradable_watch():
    mgr = _manager()
    rows = pd.DataFrame(
        [
            {"timestamp": "2024-01-01T00:00:00Z", "scan_idx": 0, "pair_id": "A-B", "pvalue": 0.20, "beta": 1.0, "spread_std": 0.2, "z_abs_p95": 2.2, "reason": "ok"},
            {"timestamp": "2024-01-01T00:15:00Z", "scan_idx": 1, "pair_id": "A-B", "pvalue": 0.05, "beta": 1.0, "spread_std": 0.2, "z_abs_p95": 2.2, "reason": "ok"},
            {"timestamp": "2024-01-01T00:30:00Z", "scan_idx": 2, "pair_id": "A-B", "pvalue": 0.18, "beta": 1.0, "spread_std": 0.2, "z_abs_p95": 2.2, "reason": "ok"},
        ]
    )
    for idx in sorted(rows["scan_idx"].unique()):
        mgr.apply_scan(rows.loc[rows["scan_idx"] == idx])
    assert mgr.state_for_pair("A-B") == "WATCH"
    events = mgr.events_df()
    assert not events.empty
    assert {"watch_to_tradable", "pvalue_exit"} <= set(events["reason"].astype(str))
