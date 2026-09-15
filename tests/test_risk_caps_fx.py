"""Risk cap tests."""

from __future__ import annotations

from fx_lean_engine.risk.caps import RiskCaps, RiskManager
from fx_lean_engine.types import PortfolioRiskState, TradeIntent


def test_risk_caps_enforced() -> None:
    manager = RiskManager(
        RiskCaps(
            max_gross_leverage=0.2,
            max_pair_notional_pct_nav=0.1,
            max_symbol_notional_pct_nav=0.15,
            max_open_pairs=1,
            max_open_trend_positions=1,
        )
    )
    state = PortfolioRiskState(gross_leverage=0.15)

    intent = TradeIntent(
        engine="trend",
        action="open",
        symbol="EURUSD",
        pair=None,
        direction="LONG",
        notional_pct_nav=0.1,
        confidence=0.7,
        reason="TREND_SIGNAL",
    )
    decision = manager.evaluate_intent(intent, state)
    assert decision.approved is False
    assert decision.reason == "RISK_GROSS_LEVERAGE_CAP"


def test_symbol_notional_cap_enforced() -> None:
    manager = RiskManager(RiskCaps(max_symbol_notional_pct_nav=0.15))
    state = PortfolioRiskState(symbol_notional_pct_nav={"EURUSD": 0.1})

    intent = TradeIntent(
        engine="trend",
        action="open",
        symbol="EURUSD",
        pair=None,
        direction="LONG",
        notional_pct_nav=0.1,
        confidence=0.7,
        reason="TREND_SIGNAL",
    )
    decision = manager.evaluate_intent(intent, state)
    assert decision.approved is False
    assert decision.reason == "RISK_SYMBOL_NOTIONAL_CAP"
