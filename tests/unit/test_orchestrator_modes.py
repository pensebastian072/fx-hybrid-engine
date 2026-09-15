"""Unit tests for mode-specific gating in RegimeOrchestrator."""
from __future__ import annotations

import pandas as pd

from fx_hybrid_engine.engines.types import Direction, EngineOutput, EngineType, Signal
from fx_hybrid_engine.regime.orchestrator import RegimeOrchestrator
from fx_hybrid_engine.utils.config import RegimeConfig, RiskConfig


def _outputs(ts: pd.Timestamp) -> tuple[EngineOutput, EngineOutput]:
    pairs = EngineOutput(
        engine=EngineType.PAIRS,
        timestamp=ts,
        signals=[Signal("EURUSD", Direction.LONG, 0.2, EngineType.PAIRS, ts)],
    )
    trend = EngineOutput(
        engine=EngineType.TREND,
        timestamp=ts,
        signals=[Signal("EURUSD", Direction.SHORT, 0.4, EngineType.TREND, ts)],
    )
    return pairs, trend


def test_pairs_only_allows_pairs_even_in_trend_regime():
    ts = pd.Timestamp("2024-01-01", tz="UTC")
    orch = RegimeOrchestrator(RegimeConfig(), RiskConfig())
    orch._current_state = "TREND"  # noqa: SLF001
    pairs, trend = _outputs(ts)
    gated = orch.gate(pairs, trend, ts, mode="pairs_only")
    assert any(s.engine == EngineType.PAIRS and s.is_active() for s in gated)
    assert all(s.engine != EngineType.TREND for s in gated if s.is_active())


def test_trend_only_allows_trend_even_in_chop_regime():
    ts = pd.Timestamp("2024-01-01", tz="UTC")
    orch = RegimeOrchestrator(RegimeConfig(), RiskConfig())
    orch._current_state = "CHOP"  # noqa: SLF001
    pairs, trend = _outputs(ts)
    gated = orch.gate(pairs, trend, ts, mode="trend_only")
    assert any(s.engine == EngineType.TREND and s.is_active() for s in gated)
    assert all(s.engine != EngineType.PAIRS for s in gated if s.is_active())

