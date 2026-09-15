"""Unit tests for attribution tables and proof checks."""
from __future__ import annotations

import pandas as pd

from fx_hybrid_engine.evaluation.attribution import (
    evaluate_proof_checks,
    pnl_attribution_engine,
    pnl_attribution_engine_x_regime,
    pnl_attribution_regime,
)
from fx_hybrid_engine.utils.config import ProofGatesConfig


def _trades() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"mode": "hybrid", "engine_source": "trend", "entry_regime": "TREND", "exit_regime": "TREND", "pnl": 1.0, "pair_id": None},
            {"mode": "hybrid", "engine_source": "trend", "entry_regime": "TREND", "exit_regime": "CHOP", "pnl": 0.8, "pair_id": None},
            {"mode": "hybrid", "engine_source": "pairs", "entry_regime": "CHOP", "exit_regime": "CHOP", "pnl": 1.1, "pair_id": "EURUSD-GBPUSD"},
            {"mode": "hybrid", "engine_source": "pairs", "entry_regime": "CHOP", "exit_regime": "TREND", "pnl": 0.6, "pair_id": "EURUSD-AUDUSD"},
        ]
    )


def test_attribution_tables_non_empty():
    trades = _trades()
    assert not pnl_attribution_engine(trades).empty
    assert not pnl_attribution_regime(trades).empty
    assert not pnl_attribution_engine_x_regime(trades).empty


def test_proof_checks_pass_for_clean_signal_alignment():
    trades = _trades()
    checks = evaluate_proof_checks(trades, ProofGatesConfig())
    assert checks["checks"]["trend_pnl_in_trend"]["pass"]
    assert checks["checks"]["pairs_pnl_in_chop"]["pass"]


def test_proof_checks_ignore_optional_regime_probability_columns():
    trades = _trades().assign(
        entry_regime_prob_trend=[0.8, 0.75, 0.1, 0.2],
        entry_regime_prob_chop=[0.1, 0.2, 0.8, 0.7],
        entry_regime_prob_risk_off=[0.1, 0.05, 0.1, 0.1],
    )
    checks = evaluate_proof_checks(trades, ProofGatesConfig())
    assert checks["checks"]["trend_pnl_in_trend"]["pass"]
