"""Minimal FX pairs engine (rolling OLS + z-score)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from fx_lean_engine.types import PairsSignal, TradeIntent


@dataclass(slots=True)
class _PairState:
    spreads: deque[float]
    holding_bars: int = 0
    position: str = "FLAT"
    last_entry_z: float = 0.0


@dataclass(slots=True)
class PairsEngine:
    """Rolling OLS hedge ratio pairs engine."""

    pairs: list[tuple[str, str]]
    lookback_bars: int
    entry_z: float
    exit_z: float
    max_holding_bars: int
    notional_pct_nav: float

    _history: dict[str, deque[float]] = field(default_factory=dict)
    _state: dict[tuple[str, str], _PairState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.pairs = [(a.upper(), b.upper()) for a, b in self.pairs]
        self.lookback_bars = max(int(self.lookback_bars), 20)
        self.entry_z = max(float(self.entry_z), 0.1)
        self.exit_z = max(float(self.exit_z), 0.0)
        self.max_holding_bars = max(int(self.max_holding_bars), 1)
        self.notional_pct_nav = min(max(float(self.notional_pct_nav), 0.0), 1.0)

        symbols = sorted({symbol for pair in self.pairs for symbol in pair})
        self._history = {symbol: deque(maxlen=self.lookback_bars + 5) for symbol in symbols}
        self._state = {
            pair: _PairState(spreads=deque(maxlen=self.lookback_bars + 5))
            for pair in self.pairs
        }

    def update(
        self,
        close_snapshot: dict[str, float],
        timestamp: datetime,
        pair_status_map: dict[tuple[str, str], str] | None = None,
    ) -> tuple[list[PairsSignal], list[TradeIntent]]:
        """Update engine with close snapshot and produce signals/intents."""
        _ = timestamp

        for symbol, close in close_snapshot.items():
            key = str(symbol).upper().strip()
            if key in self._history:
                self._history[key].append(float(close))

        signals: list[PairsSignal] = []
        intents: list[TradeIntent] = []

        for pair in self.pairs:
            left, right = pair
            left_hist = self._history[left]
            right_hist = self._history[right]
            state = self._state[pair]

            if len(left_hist) < self.lookback_bars or len(right_hist) < self.lookback_bars:
                signals.append(
                    PairsSignal(
                        pair=pair,
                        zscore=0.0,
                        hedge_ratio=0.0,
                        direction="FLAT",
                        confidence=0.0,
                        pair_status=(pair_status_map or {}).get(pair, "TRADABLE"),
                    )
                )
                continue

            x = np.log(np.asarray(left_hist, dtype=float)[-self.lookback_bars :])
            y = np.log(np.asarray(right_hist, dtype=float)[-self.lookback_bars :])
            design = np.column_stack([np.ones_like(x), x])
            coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
            intercept = float(coeffs[0])
            beta = float(coeffs[1])
            spread = y[-1] - (intercept + beta * x[-1])
            state.spreads.append(float(spread))

            if len(state.spreads) < self.lookback_bars:
                zscore = 0.0
            else:
                spread_window = np.asarray(list(state.spreads)[-self.lookback_bars :], dtype=float)
                mean = float(np.mean(spread_window))
                std = float(np.std(spread_window, ddof=1)) if spread_window.size > 1 else 0.0
                zscore = 0.0 if std <= 1e-12 else (spread_window[-1] - mean) / std

            direction = "FLAT"
            reason = "PAIR_HOLD"
            pair_status = (pair_status_map or {}).get(pair, "TRADABLE")

            if pair_status != "TRADABLE":
                if state.position != "FLAT":
                    direction = "EXIT"
                    reason = "PAIR_STATUS_BLOCK_EXIT_ONLY"
                    state.position = "FLAT"
                    state.holding_bars = 0
                else:
                    direction = "FLAT"
                    reason = "PAIR_STATUS_BLOCK"
                confidence = min(abs(zscore) / max(self.entry_z, 1e-12), 2.0) / 2.0
                signals.append(
                    PairsSignal(
                        pair=pair,
                        zscore=float(zscore),
                        hedge_ratio=beta,
                        direction=direction,
                        confidence=float(confidence),
                        pair_status=pair_status,
                    )
                )
                if direction == "EXIT":
                    intents.append(
                        TradeIntent(
                            engine="pairs",
                            action="close",
                            symbol=None,
                            pair=pair,
                            direction=direction,
                            notional_pct_nav=self.notional_pct_nav,
                            confidence=float(confidence),
                            reason=reason,
                            pair_status=pair_status,
                        )
                    )
                continue

            if state.position == "FLAT":
                if zscore >= self.entry_z:
                    state.position = "SHORT_SPREAD"
                    state.holding_bars = 0
                    state.last_entry_z = float(zscore)
                    direction = "SHORT_SPREAD"
                    reason = "PAIR_ENTRY_Z"
                elif zscore <= -self.entry_z:
                    state.position = "LONG_SPREAD"
                    state.holding_bars = 0
                    state.last_entry_z = float(zscore)
                    direction = "LONG_SPREAD"
                    reason = "PAIR_ENTRY_Z"
            else:
                state.holding_bars += 1
                if state.holding_bars >= self.max_holding_bars:
                    direction = "EXIT"
                    reason = "PAIR_MAX_HOLD"
                    state.position = "FLAT"
                    state.holding_bars = 0
                elif state.position == "LONG_SPREAD" and zscore >= -self.exit_z:
                    direction = "EXIT"
                    reason = "PAIR_EXIT_Z"
                    state.position = "FLAT"
                    state.holding_bars = 0
                elif state.position == "SHORT_SPREAD" and zscore <= self.exit_z:
                    direction = "EXIT"
                    reason = "PAIR_EXIT_Z"
                    state.position = "FLAT"
                    state.holding_bars = 0
                else:
                    direction = state.position

            confidence = min(abs(zscore) / max(self.entry_z, 1e-12), 2.0) / 2.0
            signals.append(
                PairsSignal(
                    pair=pair,
                    zscore=float(zscore),
                    hedge_ratio=beta,
                    direction=direction,
                    confidence=float(confidence),
                    pair_status=pair_status,
                )
            )

            if direction in {"LONG_SPREAD", "SHORT_SPREAD", "EXIT"}:
                intents.append(
                    TradeIntent(
                        engine="pairs",
                        action="open" if direction in {"LONG_SPREAD", "SHORT_SPREAD"} else "close",
                        symbol=None,
                        pair=pair,
                        direction=direction,
                        notional_pct_nav=self.notional_pct_nav,
                        confidence=float(confidence),
                        reason=reason,
                        pair_status=pair_status,
                    )
                )

        return signals, intents
