"""Regime orchestrator tests."""

from __future__ import annotations

from fx_lean_engine.engines.regime import RegimeOrchestrator


def test_regime_orchestrator_state_probabilities() -> None:
    orchestrator = RegimeOrchestrator(symbols=["EURUSD", "GBPUSD"])

    eur = 1.1
    gbp = 1.3
    last = None
    for _ in range(120):
        eur *= 1.0002
        gbp *= 1.00015
        last = orchestrator.update({"EURUSD": eur, "GBPUSD": gbp})

    assert last is not None
    assert last.state in {"TREND", "CHOP", "RISK_OFF"}
    total = last.p_trend + last.p_chop + last.p_risk_off
    assert abs(total - 1.0) < 1e-8


def test_regime_orchestrator_hits_risk_off_under_high_vol() -> None:
    orchestrator = RegimeOrchestrator(symbols=["EURUSD", "GBPUSD"], risk_off_vol_threshold=0.003)

    eur = 1.1
    gbp = 1.3
    last = None
    for i in range(140):
        shock = 0.005 if i % 2 == 0 else -0.005
        eur *= 1.0 + shock
        gbp *= 1.0 - shock
        last = orchestrator.update({"EURUSD": eur, "GBPUSD": gbp})

    assert last is not None
    assert last.state == "RISK_OFF"
    assert last.trend_weight == 0.0
    assert last.pairs_weight == 0.0
