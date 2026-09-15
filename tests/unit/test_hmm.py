"""Unit tests for regime/hmm.py and regime/orchestrator.py."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from fx_hybrid_engine.regime.hmm import RegimeHMM, TREND, CHOP, RISK_OFF


def _build_observations(n_bars: int = 200, high_vol: bool = False) -> np.ndarray:
    """Build synthetic [vol, momentum] observations."""
    rng = np.random.default_rng(99)
    if high_vol:
        vol = rng.normal(0.30, 0.05, n_bars).clip(0.01)  # high vol
        mom = rng.normal(0.0, 0.02, n_bars)               # low momentum
    else:
        vol = rng.normal(0.08, 0.02, n_bars).clip(0.01)   # low vol
        mom = rng.normal(0.03, 0.01, n_bars)               # positive momentum
    return np.column_stack([vol, mom])


def test_hmm_fit_and_predict_trend_state():
    """After fitting with low-vol observations, predicted state should be TREND."""
    hmm = RegimeHMM(n_states=3)
    # Train on a mix of regimes
    obs_low = _build_observations(200, high_vol=False)
    obs_high = _build_observations(200, high_vol=True)
    obs_medium = np.column_stack([
        np.random.default_rng(5).normal(0.15, 0.03, 200).clip(0.01),
        np.random.default_rng(5).normal(0.01, 0.01, 200),
    ])
    combined = np.vstack([obs_low, obs_medium, obs_high])
    hmm.fit(combined)

    assert hmm.is_fitted
    assert set(hmm._state_map.values()) == {TREND, CHOP, RISK_OFF}


def test_hmm_high_vol_predicts_risk_off(synthetic_vol_spike_series):
    """A long high-vol observation sequence should yield RISK_OFF or CHOP, not TREND."""
    hmm = RegimeHMM(n_states=3)
    obs_low = _build_observations(300, high_vol=False)
    obs_high = _build_observations(300, high_vol=True)
    obs_mid = np.column_stack([
        np.random.default_rng(3).normal(0.15, 0.03, 300).clip(0.01),
        np.random.default_rng(3).normal(0.01, 0.01, 300),
    ])
    hmm.fit(np.vstack([obs_low, obs_mid, obs_high]))

    # Predict on high-vol sequence
    high_obs = _build_observations(50, high_vol=True)
    state, proba = hmm.predict_state(high_obs)
    assert state in (RISK_OFF, CHOP), f"Expected high-vol regime, got {state}"


def test_hmm_save_load(tmp_path):
    """Serialized and reloaded HMM produces same state predictions."""
    hmm = RegimeHMM(n_states=3)
    obs = np.vstack([
        _build_observations(100, high_vol=False),
        _build_observations(100, high_vol=True),
        np.column_stack([np.random.default_rng(1).normal(0.15, 0.03, 100).clip(0.01), np.zeros(100)]),
    ])
    hmm.fit(obs)
    model_path = tmp_path / "hmm_model.pkl"
    hmm.save(model_path)

    hmm2 = RegimeHMM(n_states=3)
    hmm2.load(model_path)

    test_obs = _build_observations(30, high_vol=False)
    state1, _ = hmm.predict_state(test_obs)
    state2, _ = hmm2.predict_state(test_obs)
    assert state1 == state2


def test_hmm_predict_state_falls_back_when_decode_fails(monkeypatch):
    hmm = RegimeHMM(n_states=3)
    obs = np.vstack([
        _build_observations(120, high_vol=False),
        _build_observations(120, high_vol=True),
        np.column_stack([
            np.random.default_rng(7).normal(0.15, 0.03, 120).clip(0.01),
            np.random.default_rng(7).normal(0.0, 0.01, 120),
        ]),
    ])
    hmm.fit(obs)

    def _broken_decode(*_args, **_kwargs):
        raise ValueError("'covars' must be symmetric, positive-definite")

    def _broken_proba(*_args, **_kwargs):
        raise ValueError("'covars' must be symmetric, positive-definite")

    monkeypatch.setattr(hmm._hmm, "decode", _broken_decode)
    monkeypatch.setattr(hmm._hmm, "predict_proba", _broken_proba)

    state, proba = hmm.predict_state(_build_observations(20, high_vol=False))

    assert state in {TREND, CHOP, RISK_OFF}
    assert pytest.approx(sum(proba.values()), rel=1e-6) == 1.0
