"""OpenBB-backed FX history provider."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pandas as pd


class OpenBBProvider:
    """OpenBB provider implementation.

    OpenBB support for FX cadence can vary by provider; this contract keeps the
    default scope conservative and only advertises daily bars.
    """

    name = "openbb"
    _supported = {"1d"}

    def __init__(self, provider: str = "fmp") -> None:
        self.provider = provider

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
            raise ValueError(
                f"OpenBB provider does not support frequency '{frequency}' for this profile. "
                "Use a supported source (for example data.source=lean_history for 15m)."
            )
        try:
            from openbb import obb  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError("openbb is required for data.source=openbb") from exc

        rows: list[pd.DataFrame] = []
        for symbol in symbols:
            result = obb.currency.price.historical(
                symbol=symbol,
                start_date=str(start),
                end_date=str(end),
                provider=self.provider,
                interval=frequency,
            )
            frame = result.to_df().copy()
            if frame.empty:
                continue
            frame.index = pd.to_datetime(frame.index, utc=True)
            frame.index.name = "timestamp"
            frame.columns = [str(c).lower() for c in frame.columns]
            frame = frame.reset_index()
            frame["symbol"] = symbol
            rows.append(frame[["timestamp", "symbol", "open", "high", "low", "close", "volume"]])
        if not rows:
            return pd.DataFrame(columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        out = pd.concat(rows, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
        return out

    def stream(self, symbols: list[str], frequency: str) -> Iterator[pd.DataFrame]:
        raise NotImplementedError(
            "OpenBB stream() is not implemented in Phase 1. Use get_history() for deterministic runs."
        )
