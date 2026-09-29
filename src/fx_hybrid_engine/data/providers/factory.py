"""Provider factory for FX data sources."""
from __future__ import annotations

from fx_hybrid_engine.data.providers.base import FXDataProvider
from fx_hybrid_engine.data.providers.lean_history_provider import LeanHistoryProvider
from fx_hybrid_engine.data.providers.oanda_provider import OandaProvider
from fx_hybrid_engine.data.providers.openbb_provider import OpenBBProvider


def create_provider(
    source: str,
    *,
    openbb_provider: str = "fmp",
    seed: int = 42,
) -> FXDataProvider:
    key = str(source).lower()
    if key == "openbb":
        return OpenBBProvider(provider=openbb_provider)
    if key == "lean_history":
        return LeanHistoryProvider(seed=seed)
    if key == "oanda":
        return OandaProvider()
    raise ValueError(f"Unsupported data.source '{source}'. Expected one of: openbb, lean_history, oanda")
