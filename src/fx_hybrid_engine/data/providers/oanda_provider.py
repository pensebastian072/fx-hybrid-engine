"""OANDA provider stub for Phase 1 interface completeness."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pandas as pd


class OandaProvider:
    """Interface-complete OANDA provider stub with actionable guidance."""

    name = "oanda"
    _supported = {"15m", "1h", "1d"}

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
            raise ValueError(f"oanda provider does not support frequency '{frequency}'")
        raise NotImplementedError(
            "OandaProvider is a Phase 1 stub. Configure data.source=lean_history or data.source=openbb "
            "for backtest/smoke runs, or implement OANDA credentials + request plumbing."
        )

    def stream(self, symbols: list[str], frequency: str) -> Iterator[pd.DataFrame]:
        raise NotImplementedError(
            "OandaProvider.stream is not implemented in Phase 1. "
            "Use fxhe-paper-session bootstrap with deterministic providers."
        )
