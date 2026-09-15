"""Minimal FX trend engine."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from fx_lean_engine.types import TradeIntent, TrendSignal


def _sigmoid(value: float) -> float:
    value = max(min(float(value), 50.0), -50.0)
    return 1.0 / (1.0 + np.exp(-value))


@dataclass(slots=True)
class TrendEngine:
    """Trend engine using slope + breakout + vol filter.

    Lifecycle:
    - Emits ``action="open"`` only when a new position should be opened
      (no existing position for that symbol).
    - Emits ``action="close"`` when the signal goes FLAT while a position is open.
    - Emits ``action="close"`` + ``action="open"`` on a direction reversal.
    - Calls to ``notify_fill()`` keep the internal position book in sync
      with confirmed fills from the pipeline.
    """

    symbols: list[str]
    lookback_bars: int = 40
    breakout_window: int = 20
    vol_window: int = 20
    vol_cap_pct: float = 0.01
    notional_pct_nav: float = 0.10

    _history: dict[str, deque[float]] = field(default_factory=dict)
    # Internal position book: symbol → direction ("LONG" | "SHORT")
    # Updated only via notify_fill() so it reflects confirmed fills.
    _open_positions: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.symbols = [str(symbol).upper().strip() for symbol in self.symbols]
        self.lookback_bars = max(int(self.lookback_bars), 10)
        self.breakout_window = max(int(self.breakout_window), 5)
        self.vol_window = max(int(self.vol_window), 5)
        self.vol_cap_pct = max(float(self.vol_cap_pct), 1e-6)
        self.notional_pct_nav = min(max(float(self.notional_pct_nav), 0.0), 1.0)
        self._history = {
            symbol: deque(maxlen=max(self.lookback_bars, self.breakout_window, self.vol_window) + 5)
            for symbol in self.symbols
        }
        self._open_positions = {}

    def notify_fill(self, symbol: str, action: str, direction: str = "") -> None:
        """Sync internal position book with a confirmed fill from the pipeline.

        Call this from the orchestrator whenever a trend intent is approved and
        applied so that subsequent ``update()`` calls see the correct open state.

        Args:
            symbol: Canonical FX pair symbol (e.g. ``"EURUSD"``).
            action: ``"open"`` or ``"close"``.
            direction: ``"LONG"`` or ``"SHORT"`` (required when action is ``"open"``).
        """
        sym = str(symbol).upper().strip()
        if action == "open" and str(direction).upper() in {"LONG", "SHORT"}:
            self._open_positions[sym] = str(direction).upper()
        elif action == "close":
            self._open_positions.pop(sym, None)

    def update(self, close_snapshot: dict[str, float]) -> tuple[list[TrendSignal], list[TradeIntent]]:
        """Update trend state and emit signals/intents."""
        for symbol, close in close_snapshot.items():
            key = str(symbol).upper().strip()
            if key in self._history:
                self._history[key].append(float(close))

        signals: list[TrendSignal] = []
        intents: list[TradeIntent] = []

        for symbol in self.symbols:
            history = self._history[symbol]
            direction = "FLAT"
            p_up = 0.5
            p_down = 0.5
            confidence = 0.0

            if len(history) >= self.lookback_bars:
                closes = np.asarray(list(history), dtype=float)
                lookback = closes[-self.lookback_bars :]
                x = np.arange(lookback.size, dtype=float)
                x_centered = x - np.mean(x)
                slope_num = float(np.sum(x_centered * (lookback - np.mean(lookback))))
                slope_den = float(np.sum(x_centered**2))
                slope = 0.0 if slope_den <= 1e-12 else slope_num / slope_den
                slope_pct = 0.0 if lookback[-1] == 0 else slope / lookback[-1]

                returns = np.diff(closes) / np.maximum(closes[:-1], 1e-12)
                vol = float(np.std(returns[-self.vol_window :], ddof=1)) if returns.size >= self.vol_window else float(np.std(returns))

                breakout_slice = closes[-self.breakout_window :]
                bb_min = float(np.min(breakout_slice))
                bb_max = float(np.max(breakout_slice))
                breakout = 0.5 if bb_max <= bb_min else (float(closes[-1]) - bb_min) / (bb_max - bb_min)
                breakout = min(max(breakout, 0.0), 1.0)
                breakout_centered = (breakout - 0.5) * 2.0

                vol_filter = min(max(1.0 - (vol / self.vol_cap_pct), 0.0), 1.0)
                score = (0.65 * slope_pct * 100.0 + 0.35 * breakout_centered) * (0.5 + 0.5 * vol_filter)
                p_up = float(_sigmoid(score))
                p_down = float(1.0 - p_up)
                confidence = float(abs(p_up - p_down))

                if p_up >= 0.55:
                    direction = "LONG"
                elif p_down >= 0.55:
                    direction = "SHORT"

            signals.append(
                TrendSignal(
                    symbol=symbol,
                    p_up=float(p_up),
                    p_down=float(p_down),
                    confidence=float(confidence),
                    direction=direction,
                )
            )

            current_position = self._open_positions.get(symbol)

            if current_position is not None:
                # A confirmed position is open — decide whether to close or reverse.
                if direction == "FLAT":
                    intents.append(
                        TradeIntent(
                            engine="trend",
                            action="close",
                            symbol=symbol,
                            pair=None,
                            direction="EXIT",
                            notional_pct_nav=self.notional_pct_nav,
                            confidence=float(confidence),
                            reason="TREND_FLAT",
                        )
                    )
                elif direction != current_position:
                    # Reversal: close current, then open opposite.
                    intents.append(
                        TradeIntent(
                            engine="trend",
                            action="close",
                            symbol=symbol,
                            pair=None,
                            direction="EXIT",
                            notional_pct_nav=self.notional_pct_nav,
                            confidence=float(confidence),
                            reason="TREND_REVERSAL",
                        )
                    )
                    intents.append(
                        TradeIntent(
                            engine="trend",
                            action="open",
                            symbol=symbol,
                            pair=None,
                            direction=direction,
                            notional_pct_nav=self.notional_pct_nav,
                            confidence=float(confidence),
                            reason="TREND_SIGNAL",
                        )
                    )
                # else: same direction — position already open, nothing to do.
            elif direction in {"LONG", "SHORT"}:
                # No confirmed position — emit a new open intent.
                intents.append(
                    TradeIntent(
                        engine="trend",
                        action="open",
                        symbol=symbol,
                        pair=None,
                        direction=direction,
                        notional_pct_nav=self.notional_pct_nav,
                        confidence=float(confidence),
                        reason="TREND_SIGNAL",
                    )
                )

        return signals, intents
