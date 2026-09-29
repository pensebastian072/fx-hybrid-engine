"""Rolling feature store — updated per bar."""
from __future__ import annotations

from collections import defaultdict

import pandas as pd


class FeatureStore:
    """Maintains a rolling time-series of features for each symbol.

    Features are stored as DataFrames keyed by symbol name.
    """

    def __init__(self) -> None:
        self._store: dict[str, pd.DataFrame] = defaultdict(pd.DataFrame)

    def update(self, symbol: str, timestamp: pd.Timestamp, features: dict[str, float]) -> None:
        """Append a new row of features for a symbol at timestamp."""
        row = pd.DataFrame([features], index=[timestamp])
        existing = self._store[symbol]
        self._store[symbol] = pd.concat([existing, row]) if not existing.empty else row

    def get(self, symbol: str) -> pd.DataFrame:
        """Return all stored features for a symbol."""
        return self._store.get(symbol, pd.DataFrame())

    def latest(self, symbol: str) -> dict[str, float] | None:
        """Return the most recent feature row for a symbol."""
        df = self._store.get(symbol)
        if df is None or df.empty:
            return None
        return df.iloc[-1].to_dict()

    def symbols(self) -> list[str]:
        return list(self._store.keys())
