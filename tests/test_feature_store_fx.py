"""Feature store tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_lean_engine.data.feature_store import FeatureStore
from fx_lean_engine.types import Bar


def test_feature_store_outputs_finite_vectors_after_warmup() -> None:
    store = FeatureStore(warmup_bars=20)
    start = datetime(2025, 1, 1, tzinfo=UTC)

    last_vector = None
    close = 1.0
    for i in range(80):
        close *= 1.0005 if i % 2 == 0 else 0.9997
        ts = start + timedelta(minutes=15 * i)
        last_vector = store.update(
            Bar(
                symbol="EURUSD",
                start=ts,
                end=ts + timedelta(minutes=15),
                open=close * 0.999,
                high=close * 1.001,
                low=close * 0.998,
                close=close,
                volume=1000.0,
            )
        )

    assert last_vector is not None
    assert last_vector.vol_20_pct >= 0.0
    assert -20.0 < last_vector.zret_20 < 20.0

    row = store.latest_feature_rows()[0]
    assert "close" in row
    assert "ret_1" in row
    assert "log_ret_1" in row
    assert "vol_20_pct" in row
    assert "zret_20" in row
    assert "range_pct" in row
    assert "raw_spread" not in row
