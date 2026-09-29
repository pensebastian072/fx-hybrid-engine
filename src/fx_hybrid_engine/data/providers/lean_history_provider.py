"""Lean history provider abstraction.

This Phase 1 implementation is deterministic and local-first for testability.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date

import numpy as np
import pandas as pd


def _freq_to_pandas(frequency: str) -> str:
    mapping = {"15m": "15min", "1h": "1h", "1d": "1D"}
    key = str(frequency).lower()
    if key not in mapping:
        raise ValueError(f"Unsupported frequency '{frequency}' for lean_history")
    return mapping[key]


class LeanHistoryProvider:
    """Deterministic history provider matching intended Lean cadence semantics."""

    name = "lean_history"
    _supported = {"15m", "1h", "1d"}

    def __init__(self, seed: int = 42) -> None:
        self.seed = int(seed)

    def supports_frequency(self, frequency: str) -> bool:
        return str(frequency).lower() in self._supported

    def get_history(
        self,
        symbols: list[str],
        start: date | str,
        end: date | str,
        frequency: str,
    ) -> pd.DataFrame:
        if not self.supports_frequency(frequency):
            raise ValueError(f"lean_history does not support frequency '{frequency}'")
        freq = _freq_to_pandas(frequency)
        idx = pd.date_range(start=str(start), end=str(end), freq=freq, tz=UTC)
        if len(idx) < 5:
            return pd.DataFrame(columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"])

        frames: list[pd.DataFrame] = []
        for i, symbol in enumerate(symbols):
            symbol_seed = self.seed + (i + 1) * 997
            rng = np.random.default_rng(symbol_seed)
            common = np.cumsum(rng.normal(0.0, 0.0005, len(idx)))
            drift = np.linspace(0.0, 0.02 * ((i % 3) - 1), len(idx))
            close = 1.0 + common + drift
            close = np.clip(close, 0.2, None)
            open_px = close * (1.0 + rng.normal(0.0, 0.0002, len(idx)))
            high = np.maximum(open_px, close) * (1.0 + np.abs(rng.normal(0.0004, 0.0001, len(idx))))
            low = np.minimum(open_px, close) * (1.0 - np.abs(rng.normal(0.0004, 0.0001, len(idx))))
            vol = rng.integers(100, 1200, size=len(idx))
            frame = pd.DataFrame(
                {
                    "timestamp": idx,
                    "symbol": symbol,
                    "open": open_px,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": vol,
                }
            )
            frames.append(frame)
        return pd.concat(frames, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(drop=True)

    def stream(self, symbols: list[str], frequency: str) -> Iterator[pd.DataFrame]:
        history = self.get_history(symbols, start="2025-01-01", end="2025-01-03", frequency=frequency)
        for ts, frame in history.groupby("timestamp", sort=True):
            yield frame.assign(timestamp=ts)
