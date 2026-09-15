"""Unit tests for robustness perturbation reproducibility."""
from __future__ import annotations

import numpy as np

from fx_hybrid_engine.evaluation.robustness import jitter_config
from fx_hybrid_engine.utils.config import (
    DataConfig,
    EngineConfig,
    ExecutionCostsConfig,
    PairsConfig,
    ProofGatesConfig,
    RegimeConfig,
    RiskConfig,
    RobustnessConfig,
    TrendConfig,
    WalkforwardConfig,
)


def _cfg() -> EngineConfig:
    return EngineConfig(
        universe={"pairs": [["EURUSD", "GBPUSD"]], "trend_symbols": ["EURUSD"]},
        pairs=PairsConfig(pairs=[["EURUSD", "GBPUSD"]]),
        trend=TrendConfig(),
        regime=RegimeConfig(),
        risk=RiskConfig(),
        data=DataConfig(),
        walkforward=WalkforwardConfig(),
        execution_costs=ExecutionCostsConfig(),
        robustness=RobustnessConfig(random_seed=7),
        proof_gates=ProofGatesConfig(),
    )


def test_jitter_config_is_reproducible_with_fixed_seed():
    base1 = _cfg()
    base2 = _cfg()
    r1 = np.random.default_rng(11)
    r2 = np.random.default_rng(11)
    c1 = jitter_config(base1, r1)
    c2 = jitter_config(base2, r2)
    assert c1.pairs.entry_zscore == c2.pairs.entry_zscore
    assert c1.pairs.cointegration_pvalue_threshold == c2.pairs.cointegration_pvalue_threshold
    assert c1.trend.signal_threshold == c2.trend.signal_threshold

