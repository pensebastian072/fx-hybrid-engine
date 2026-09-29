"""Provider interfaces for FX history/stream ingestion."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Protocol

import pandas as pd


class FXDataProvider(Protocol):
    """Unified FX provider protocol."""

    name: str

    def supports_frequency(self, frequency: str) -> bool:
        """Return True when the provider can serve the requested bar cadence."""

    def get_history(
        self,
        symbols: list[str],
        start: date | str,
        end: date | str,
        frequency: str,
    ) -> pd.DataFrame:
        """Fetch long-form bars with canonical columns and UTC timestamps."""

    def stream(self, symbols: list[str], frequency: str) -> Iterator[pd.DataFrame]:
        """Yield streaming long-form bars in canonical schema."""
