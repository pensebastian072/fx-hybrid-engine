"""Portfolio builder: aggregates gated signals → target weights."""
from __future__ import annotations
import logging
import pandas as pd

from fx_hybrid_engine.engines.types import Direction, Signal
from fx_hybrid_engine.risk.position_sizing import apply_vol_sizing
from fx_hybrid_engine.utils.config import RiskConfig

logger = logging.getLogger("fxhe.portfolio.builder")


class PortfolioBuilder:
    """Converts a list of gated Signals into a target weights dictionary.

    Target weights are signed floats: positive = long, negative = short.
    The builder also applies vol-targeting and enforces max_leverage.
    """

    def __init__(self, config: RiskConfig) -> None:
        self.config = config

    def build(
        self,
        signals: list[Signal],
        realized_vols: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Aggregate signals and return {symbol: target_weight}.

        Parameters
        ----------
        signals:
            Gated signals from the regime orchestrator.
        realized_vols:
            Optional per-symbol annualized vol for vol-targeting.
            If None, vol-targeting is skipped.
        """
        if not signals:
            return {}

        # Aggregate: if multiple signals exist for a symbol, sum signed sizes
        raw: dict[str, float] = {}
        for sig in signals:
            if not sig.is_active():
                raw[sig.symbol] = 0.0
                continue
            signed = sig.size if sig.direction == Direction.LONG else -sig.size
            raw[sig.symbol] = raw.get(sig.symbol, 0.0) + signed

        # Cap individual positions
        capped = {
            sym: max(-self.config.max_position_pct_individual, min(self.config.max_position_pct_individual, w))
            if hasattr(self.config, "max_position_pct_individual")
            else w
            for sym, w in raw.items()
        }

        # Apply vol targeting if vols provided
        if realized_vols:
            abs_weights = {sym: abs(w) for sym, w in capped.items()}
            scaled_abs = apply_vol_sizing(abs_weights, realized_vols, self.config)
            # Preserve signs
            target = {sym: scaled_abs[sym] * (1 if capped[sym] >= 0 else -1) for sym in capped}
        else:
            target = dict(capped)

        # Final leverage cap
        total = sum(abs(v) for v in target.values())
        if total > self.config.max_leverage:
            factor = self.config.max_leverage / total
            target = {k: v * factor for k, v in target.items()}

        logger.debug("Target weights: %s", target)
        return target
