"""Conservative runtime risk caps."""

from __future__ import annotations

from dataclasses import dataclass

from fx_lean_engine.types import PortfolioRiskState, RiskDecision, TradeIntent


@dataclass(slots=True)
class RiskCaps:
    """Risk cap config."""

    max_gross_leverage: float = 2.0
    max_pair_notional_pct_nav: float = 0.25
    max_symbol_notional_pct_nav: float = 0.15
    max_open_pairs: int = 2
    max_open_trend_positions: int = 3


class RiskManager:
    """Validate intents against cap limits."""

    def __init__(self, caps: RiskCaps):
        self.caps = caps

    @staticmethod
    def _pair_key(pair: tuple[str, str] | None) -> str:
        if pair is None:
            return ""
        left = str(pair[0]).upper().strip()
        right = str(pair[1]).upper().strip()
        return f"{left}-{right}" if left <= right else f"{right}-{left}"

    def evaluate_intent(self, intent: TradeIntent, state: PortfolioRiskState) -> RiskDecision:
        """Check one intent against limits."""
        if intent.action == "close":
            return RiskDecision(approved=True, reason="RISK_OK_CLOSE")

        proposed_gross = state.gross_leverage + abs(intent.notional_pct_nav)
        if proposed_gross > self.caps.max_gross_leverage + 1e-12:
            return RiskDecision(approved=False, reason="RISK_GROSS_LEVERAGE_CAP")

        if intent.pair is not None:
            pair_key = self._pair_key(intent.pair)
            existing_pair = float((state.pair_notional_pct_nav or {}).get(pair_key, 0.0))
            if existing_pair + abs(intent.notional_pct_nav) > self.caps.max_pair_notional_pct_nav + 1e-12:
                return RiskDecision(approved=False, reason="RISK_PAIR_NOTIONAL_CAP")
            if existing_pair <= 1e-12 and state.open_pairs >= self.caps.max_open_pairs:
                return RiskDecision(approved=False, reason="RISK_OPEN_PAIRS_CAP")

        if intent.symbol is not None:
            key = intent.symbol.upper()
            existing = float((state.symbol_notional_pct_nav or {}).get(key, 0.0))
            if existing + abs(intent.notional_pct_nav) > self.caps.max_symbol_notional_pct_nav + 1e-12:
                return RiskDecision(approved=False, reason="RISK_SYMBOL_NOTIONAL_CAP")

        if intent.engine == "trend" and intent.action == "open":
            existing = float((state.symbol_notional_pct_nav or {}).get(str(intent.symbol or "").upper(), 0.0))
            if existing <= 1e-12 and state.open_trend_positions >= self.caps.max_open_trend_positions:
                return RiskDecision(approved=False, reason="RISK_OPEN_TREND_POSITIONS_CAP")

        return RiskDecision(approved=True, reason="RISK_OK")

    def apply_approved_intent(self, intent: TradeIntent, state: PortfolioRiskState) -> None:
        """Update in-memory risk state for approved intent."""
        notional = abs(float(intent.notional_pct_nav))
        pair_key = self._pair_key(intent.pair)
        symbol_key = str(intent.symbol or "").upper().strip()

        if intent.action == "close":
            state.gross_leverage = max(float(state.gross_leverage) - notional, 0.0)

            if pair_key:
                existing_pair = float((state.pair_notional_pct_nav or {}).get(pair_key, 0.0))
                if existing_pair > 0.0:
                    next_pair = max(existing_pair - notional, 0.0)
                    if next_pair <= 1e-12:
                        state.pair_notional_pct_nav.pop(pair_key, None)
                        state.open_pairs = max(int(state.open_pairs) - 1, 0)
                    else:
                        state.pair_notional_pct_nav[pair_key] = next_pair

            if symbol_key:
                existing_symbol = float((state.symbol_notional_pct_nav or {}).get(symbol_key, 0.0))
                if existing_symbol > 0.0:
                    next_symbol = max(existing_symbol - notional, 0.0)
                    if next_symbol <= 1e-12:
                        state.symbol_notional_pct_nav.pop(symbol_key, None)
                        if intent.engine == "trend":
                            state.open_trend_positions = max(int(state.open_trend_positions) - 1, 0)
                    else:
                        state.symbol_notional_pct_nav[symbol_key] = next_symbol
            return

        state.gross_leverage = float(state.gross_leverage) + notional

        if pair_key:
            existing_pair = float((state.pair_notional_pct_nav or {}).get(pair_key, 0.0))
            if existing_pair <= 1e-12:
                state.open_pairs = int(state.open_pairs) + 1
            state.pair_notional_pct_nav[pair_key] = existing_pair + notional

        if symbol_key:
            existing_symbol = float((state.symbol_notional_pct_nav or {}).get(symbol_key, 0.0))
            if intent.engine == "trend" and existing_symbol <= 1e-12:
                state.open_trend_positions = int(state.open_trend_positions) + 1
            state.symbol_notional_pct_nav[symbol_key] = existing_symbol + notional
