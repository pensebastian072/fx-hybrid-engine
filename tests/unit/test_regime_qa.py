"""Unit tests for regime QA summaries and transition events."""
from __future__ import annotations

import pandas as pd

from fx_hybrid_engine.reporting.regime_qa import regime_events, summarize_regime_qa
from fx_hybrid_engine.utils.config import RegimeQAConfig


def test_regime_qa_summary_and_events():
    df = pd.DataFrame(
        [
            {"timestamp": "2024-01-01T00:00:00Z", "regime_label": "CHOP", "TREND": 0.1, "CHOP": 0.8, "RISK_OFF": 0.1},
            {"timestamp": "2024-01-01T00:15:00Z", "regime_label": "TREND", "TREND": 0.7, "CHOP": 0.2, "RISK_OFF": 0.1},
            {"timestamp": "2024-01-01T00:30:00Z", "regime_label": "TREND", "TREND": 0.8, "CHOP": 0.1, "RISK_OFF": 0.1},
            {"timestamp": "2024-01-01T00:45:00Z", "regime_label": "RISK_OFF", "TREND": 0.1, "CHOP": 0.1, "RISK_OFF": 0.8},
        ]
    )
    events = regime_events(df)
    assert len(events) == 2
    summary = summarize_regime_qa(df, cfg=RegimeQAConfig())
    assert summary["n_bars"] == 4
    assert "occupancy" in summary
    assert "checks" in summary
    assert summary["checks"]["posterior_sum_ok"]
