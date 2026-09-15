"""Integration test: mixed-regime simulation verifies engine gating."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from fx_hybrid_engine.engines.pairs import PairsEngine
from fx_hybrid_engine.engines.trend import TrendEngine
from fx_hybrid_engine.engines.types import Direction, EngineType
from fx_hybrid_engine.regime.hmm import RegimeHMM, TREND, CHOP, RISK_OFF
from fx_hybrid_engine.regime.orchestrator import RegimeOrchestrator
from fx_hybrid_engine.portfolio.builder import PortfolioBuilder
from fx_hybrid_engine.utils.config import (
    EngineConfig,
    PairsConfig,
    TrendConfig,
    RegimeConfig,
    RiskConfig,
    DataConfig,
)


pytestmark = pytest.mark.integration


def _make_config() -> EngineConfig:
    return EngineConfig(
        universe={"pairs": [["A", "B"]], "trend_symbols": ["EURUSD"]},
        pairs=PairsConfig(pairs=[["A", "B"]], spread_window=40, entry_zscore=2.0, exit_zscore=1.0),
        trend=TrendConfig(feature_lookback=20, signal_threshold=0.60, sma_fast=20, sma_slow=50),
        regime=RegimeConfig(n_states=3, obs_window=20, vol_window=15),
        risk=RiskConfig(max_leverage=3.0, stop_loss_pct=0.02, drawdown_kill_pct=0.05),
        data=DataConfig(),
    )


def _make_data(n: int = 300) -> dict[str, pd.DataFrame]:
    """Build synthetic multi-symbol bar data."""
    rng = np.random.default_rng(77)
    dates = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    # Cointegrated pair A, B
    common = np.cumsum(rng.normal(0, 0.01, n))
    idio_b = np.cumsum(rng.normal(0, 0.001, n))
    price_a = pd.Series(np.exp(common + 5), index=dates)
    price_b = pd.Series(np.exp((common / 1.5) + idio_b + 5), index=dates)
    # Trending EURUSD
    trend_seg = np.linspace(1.1, 1.2, n // 2)
    flat_seg = np.full(n - n // 2, 1.2)
    eurusd = pd.Series(np.concatenate([trend_seg, flat_seg]) + rng.normal(0, 0.001, n), index=dates)

    return {
        "A": pd.DataFrame({"close": price_a, "open": price_a, "high": price_a * 1.001, "low": price_a * 0.999}),
        "B": pd.DataFrame({"close": price_b, "open": price_b, "high": price_b * 1.001, "low": price_b * 0.999}),
        "EURUSD": pd.DataFrame({"close": eurusd, "open": eurusd, "high": eurusd * 1.001, "low": eurusd * 0.999}),
    }


def test_end_to_end_pipeline_no_crash():
    """Full pipeline (fit → generate → gate → build) runs without exceptions."""
    cfg = _make_config()
    data = _make_data(300)
    timestamp = list(data.values())[0].index[-1]

    # Engines
    pairs_engine = PairsEngine(cfg.pairs)
    pairs_engine.fit(data)
    trend_engine = TrendEngine(cfg.trend)
    trend_engine.train(data)

    pairs_out = pairs_engine.generate(data, timestamp)
    trend_out = trend_engine.generate(data, timestamp)

    # Regime orchestrator (no pre-trained model → defaults to CHOP)
    orchestrator = RegimeOrchestrator(cfg.regime, cfg.risk)
    state = orchestrator.update_regime(data)
    assert state in (TREND, CHOP, RISK_OFF)

    gated = orchestrator.gate(pairs_out, trend_out, timestamp)
    assert isinstance(gated, list)

    # Portfolio
    builder = PortfolioBuilder(cfg.risk)
    weights = builder.build(gated)
    assert isinstance(weights, dict)

    # Leverage constraint
    total_exposure = sum(abs(v) for v in weights.values())
    assert total_exposure <= cfg.risk.max_leverage + 1e-6


def test_chop_regime_suppresses_trend_signals():
    """In CHOP regime, trend signals should be gated out."""
    cfg = _make_config()
    data = _make_data(300)
    timestamp = list(data.values())[0].index[-1]

    pairs_engine = PairsEngine(cfg.pairs)
    pairs_engine.fit(data)
    trend_engine = TrendEngine(cfg.trend)

    pairs_out = pairs_engine.generate(data, timestamp)
    trend_out = trend_engine.generate(data, timestamp)

    orchestrator = RegimeOrchestrator(cfg.regime, cfg.risk)
    # Force CHOP state directly
    orchestrator._current_state = CHOP

    gated = orchestrator.gate(pairs_out, trend_out, timestamp)
    # No gated signal should come from the trend engine
    trend_signals = [s for s in gated if s.engine == EngineType.TREND and s.is_active()]
    assert len(trend_signals) == 0


def test_trend_regime_suppresses_pairs_signals():
    """In TREND regime, pairs signals should be gated out."""
    cfg = _make_config()
    data = _make_data(300)
    timestamp = list(data.values())[0].index[-1]

    pairs_engine = PairsEngine(cfg.pairs)
    pairs_engine.fit(data)
    trend_engine = TrendEngine(cfg.trend)

    pairs_out = pairs_engine.generate(data, timestamp)
    trend_out = trend_engine.generate(data, timestamp)

    orchestrator = RegimeOrchestrator(cfg.regime, cfg.risk)
    orchestrator._current_state = TREND

    gated = orchestrator.gate(pairs_out, trend_out, timestamp)
    pairs_signals = [s for s in gated if s.engine == EngineType.PAIRS and s.is_active()]
    assert len(pairs_signals) == 0


def test_risk_off_regime_reduces_size():
    """In RISK_OFF regime, all signals should be reduced in size."""
    cfg = _make_config()
    data = _make_data(300)
    timestamp = list(data.values())[0].index[-1]

    pairs_engine = PairsEngine(cfg.pairs)
    pairs_engine.fit(data)
    trend_engine = TrendEngine(cfg.trend)

    pairs_out = pairs_engine.generate(data, timestamp)
    trend_out = trend_engine.generate(data, timestamp)

    orchestrator = RegimeOrchestrator(cfg.regime, cfg.risk)
    orchestrator._current_state = RISK_OFF

    gated = orchestrator.gate(pairs_out, trend_out, timestamp)
    active = [s for s in gated if s.is_active()]
    # All active sizes should be ≤ risk_off_size_multiplier * max_position_pct
    for sig in active:
        assert sig.size <= cfg.risk.risk_off_size_multiplier + 1e-6
