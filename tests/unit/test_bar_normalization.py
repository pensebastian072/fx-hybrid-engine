"""Unit tests for bar normalization and health diagnostics."""
from __future__ import annotations

import pandas as pd

from fx_hybrid_engine.data.alignment import normalize_and_consolidate, normalize_universe


def test_normalizer_removes_duplicates_and_sorts_index():
    idx = pd.to_datetime(
        [
            "2024-01-01T00:15:00Z",
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:30:00Z",
        ],
        utc=True,
    )
    frame = pd.DataFrame(
        {
            "open": [1.0, 1.0, 1.01, 1.02],
            "high": [1.1, 1.1, 1.11, 1.12],
            "low": [0.9, 0.9, 0.91, 0.92],
            "close": [1.05, 1.04, 1.045, 1.06],
            "volume": [100, 100, 150, 200],
        },
        index=idx,
    )
    normalized, health = normalize_and_consolidate(frame, symbol="EURUSD", target_frequency="15m")
    assert normalized.index.is_monotonic_increasing
    assert health["duplicates_removed"] == 1
    assert health["non_monotonic_fixed"] is True


def test_gap_detection_surfaces_health_rows():
    idx = pd.to_datetime(
        [
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:15:00Z",
            "2024-01-01T00:45:00Z",
        ],
        utc=True,
    )
    frame = pd.DataFrame(
        {
            "open": [1.0, 1.01, 1.03],
            "high": [1.1, 1.11, 1.13],
            "low": [0.9, 0.91, 0.93],
            "close": [1.05, 1.06, 1.08],
            "volume": [100, 110, 120],
        },
        index=idx,
    )
    _, health = normalize_universe({"EURUSD": frame}, target_frequency="15m")
    assert not health.empty
    assert int(health.loc[0, "gap_count"]) >= 1
