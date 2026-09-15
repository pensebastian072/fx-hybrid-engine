"""Pairs (statistical arbitrage) engine."""
from __future__ import annotations
import logging
import pandas as pd

from fx_hybrid_engine.engines.types import Direction, EngineOutput, EngineType, Signal
from fx_hybrid_engine.features.spread import (
    compute_spread,
    hedge_ratio,
    is_cointegrated,
    zscore,
)
from fx_hybrid_engine.utils.config import PairsConfig

logger = logging.getLogger("fxhe.engines.pairs")


class PairsEngine:
    """Generates mean-reversion signals for cointegrated currency pairs.

    For each candidate pair, it:
    1. Verifies cointegration (Engle-Granger) on training data.
    2. Computes a rolling spread and z-score.
    3. Emits long-A/short-B when z < -entry_zscore,
       short-A/long-B when z > +entry_zscore,
       and flat when |z| < exit_zscore.
    """

    def __init__(self, config: PairsConfig) -> None:
        self.config = config
        # Cached hedge ratios for validated pairs: (sym_a, sym_b) → beta
        self._betas: dict[tuple[str, str], float] = {}
        self._pair_state_map: dict[str, str] = {}
        self._pair_state_timeline: dict[str, pd.Series] = {}

    def fit(self, data: dict[str, pd.DataFrame]) -> None:
        """Run cointegration tests and estimate hedge ratios on training data."""
        for pair in self.config.pairs:
            sym_a, sym_b = pair[0], pair[1]
            if sym_a not in data or sym_b not in data:
                logger.warning("Pair (%s, %s) missing from data — skipping", sym_a, sym_b)
                continue
            close_a = data[sym_a]["close"]
            close_b = data[sym_b]["close"]
            cointegrated, pval = is_cointegrated(
                close_a,
                close_b,
                self.config.cointegration_pvalue_threshold,
                method=getattr(self.config, "cointegration_method", "engle_granger"),
            )
            if not cointegrated:
                logger.info("Pair (%s, %s) not cointegrated (p=%.3f) — skipping", sym_a, sym_b, pval)
                continue
            beta = hedge_ratio(close_a, close_b)
            self._betas[(sym_a, sym_b)] = beta
            logger.info("Pair (%s, %s) cointegrated (p=%.3f), beta=%.4f", sym_a, sym_b, pval, beta)

    @property
    def active_pairs(self) -> list[tuple[str, str]]:
        return list(self._betas.keys())

    def set_pair_states(self, state_map: dict[str, str] | None) -> None:
        self._pair_state_map = {str(k): str(v) for k, v in (state_map or {}).items()}

    def set_pair_state_timeline(self, timeline: dict[str, pd.Series] | None) -> None:
        self._pair_state_timeline = {}
        for pair_id, series in (timeline or {}).items():
            s = pd.Series(series).copy()
            if not isinstance(s.index, pd.DatetimeIndex):
                s.index = pd.to_datetime(s.index, utc=True)
            else:
                s.index = pd.to_datetime(s.index, utc=True)
            s = s.sort_index()
            self._pair_state_timeline[str(pair_id)] = s

    def _state_for(self, pair_id: str, timestamp: pd.Timestamp) -> str:
        timeline = self._pair_state_timeline.get(pair_id)
        if timeline is not None and len(timeline) > 0:
            ts = pd.Timestamp(timestamp)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            eligible = timeline.loc[timeline.index <= ts]
            if not eligible.empty:
                return str(eligible.iloc[-1])
        return str(self._pair_state_map.get(pair_id, "TRADABLE"))

    def generate(self, data: dict[str, pd.DataFrame], timestamp: pd.Timestamp) -> EngineOutput:
        """Generate signals for all active pairs at timestamp."""
        output = EngineOutput(engine=EngineType.PAIRS, timestamp=timestamp)

        for (sym_a, sym_b), beta in self._betas.items():
            if sym_a not in data or sym_b not in data:
                continue
            close_a = data[sym_a]["close"]
            close_b = data[sym_b]["close"]

            spread = compute_spread(close_a, close_b, beta)
            z = zscore(spread, self.config.spread_window)

            if z.empty or pd.isna(z.iloc[-1]):
                continue

            current_z = z.iloc[-1]
            size = self.config.max_position_pct
            pair_id = f"{sym_a}-{sym_b}"
            pair_state = self._state_for(pair_id, timestamp)

            if current_z < -self.config.entry_zscore and pair_state == "TRADABLE":
                # Spread too low: go long A, short B (beta-neutral)
                output.signals.append(Signal(sym_a, Direction.LONG, size, EngineType.PAIRS, timestamp, confidence=abs(current_z) / self.config.entry_zscore, metadata={"pair_id": pair_id}))
                output.signals.append(Signal(sym_b, Direction.SHORT, size * beta, EngineType.PAIRS, timestamp, confidence=abs(current_z) / self.config.entry_zscore, metadata={"pair_id": pair_id}))
            elif current_z > self.config.entry_zscore and pair_state == "TRADABLE":
                # Spread too high: short A, long B
                output.signals.append(Signal(sym_a, Direction.SHORT, size, EngineType.PAIRS, timestamp, confidence=abs(current_z) / self.config.entry_zscore, metadata={"pair_id": pair_id}))
                output.signals.append(Signal(sym_b, Direction.LONG, size * beta, EngineType.PAIRS, timestamp, confidence=abs(current_z) / self.config.entry_zscore, metadata={"pair_id": pair_id}))
            elif abs(current_z) < self.config.exit_zscore:
                # Exit zone: flat both legs
                for sym in (sym_a, sym_b):
                    output.signals.append(Signal(sym, Direction.FLAT, 0.0, EngineType.PAIRS, timestamp, metadata={"pair_id": pair_id, "pair_state": pair_state}))

        return output
