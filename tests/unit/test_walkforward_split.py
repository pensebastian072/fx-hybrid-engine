"""Unit tests for walk-forward split generation."""
from __future__ import annotations

import pandas as pd

from fx_hybrid_engine.evaluation.walkforward import generate_walkforward_splits


def test_generate_walkforward_splits_respects_max_splits():
    idx = pd.date_range("2020-01-01", "2022-12-31", freq="B", tz="UTC")
    splits = generate_walkforward_splits(
        index=idx,
        train_window_days=180,
        test_window_days=60,
        step_days=30,
        max_splits=3,
    )
    assert len(splits) == 3
    assert splits[0]["train_start"] < splits[0]["train_end"] < splits[0]["test_end"]
    assert int(splits[0]["n_train_bars"]) > 0
    assert int(splits[0]["n_test_bars"]) > 0

