"""HMM regime engine tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("hmmlearn")

from fx_lean_engine.engines.regime_hmm import RegimeEngineHMM
from fx_lean_engine.types import FeatureVector


def _snapshot(ts: datetime, log_ret: float, vol: float, rng: float) -> dict[str, FeatureVector]:
    return {
        "EURUSD": FeatureVector(
            symbol="EURUSD",
            timestamp=ts,
            close=1.1,
            ret_1=log_ret,
            log_ret_1=log_ret,
            vol_20_pct=vol,
            zret_20=0.0,
            range_pct=rng,
        ),
        "GBPUSD": FeatureVector(
            symbol="GBPUSD",
            timestamp=ts,
            close=1.3,
            ret_1=log_ret * 0.8,
            log_ret_1=log_ret * 0.8,
            vol_20_pct=vol * 1.1,
            zret_20=0.0,
            range_pct=rng * 1.1,
        ),
    }


def test_regime_hmm_probabilities_sum_to_one_and_emit_artifacts() -> None:
    engine = RegimeEngineHMM(
        symbols=["EURUSD", "GBPUSD"],
        lookback_bars=60,
        retrain_frequency="daily",
        n_iter=80,
        random_state=42,
    )

    start = datetime(2025, 1, 1, tzinfo=UTC)
    last_state = None
    for i in range(180):
        ts = start + timedelta(minutes=15 * i)
        if i < 60:
            row = _snapshot(ts, log_ret=0.0003, vol=0.0015, rng=0.001)
        elif i < 120:
            row = _snapshot(ts, log_ret=0.0, vol=0.0030, rng=0.002)
        else:
            row = _snapshot(ts, log_ret=-0.0004, vol=0.0060, rng=0.004)
        last_state = engine.update({"EURUSD": 1.1, "GBPUSD": 1.3}, feature_snapshot=row, timestamp=ts)
        total = last_state.p_trend + last_state.p_chop + last_state.p_risk_off
        assert abs(total - 1.0) < 1e-6

    assert last_state is not None
    drained = engine.drain_artifacts()
    assert drained["regime_posteriors"]
    assert drained["regime_hmm_params"] is not None
    assert drained["regime_state_map"]


def test_regime_hmm_mapping_is_deterministic_with_seed() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)

    def _run() -> dict[str, object] | None:
        engine = RegimeEngineHMM(
            symbols=["EURUSD", "GBPUSD"],
            lookback_bars=50,
            retrain_frequency="daily",
            n_iter=80,
            random_state=42,
        )
        for i in range(150):
            ts = start + timedelta(minutes=15 * i)
            log_ret = 0.00025 if i % 3 == 0 else -0.00015
            vol = 0.001 + (i % 7) * 0.0005
            rng = 0.001 + (i % 5) * 0.0004
            engine.update({"EURUSD": 1.1, "GBPUSD": 1.3}, feature_snapshot=_snapshot(ts, log_ret, vol, rng), timestamp=ts)
        return engine.drain_artifacts().get("regime_state_map")

    first = _run()
    second = _run()
    assert first == second
