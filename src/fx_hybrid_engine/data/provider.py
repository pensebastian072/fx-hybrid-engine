"""Unified FX bar provider compatibility layer."""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from fx_hybrid_engine.data.providers.factory import create_provider

logger = logging.getLogger("fxhe.data.provider")

_BAR_COLUMNS = ["open", "high", "low", "close", "volume"]


def _canonicalize_long_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", *_BAR_COLUMNS])
    out = frame.copy()
    out.columns = [str(c).lower() for c in out.columns]
    required = {"timestamp", "symbol", "open", "high", "low", "close"}
    missing = sorted(required.difference(set(out.columns)))
    if missing:
        raise ValueError(f"Provider output missing required columns: {missing}")
    if "volume" not in out.columns:
        out["volume"] = pd.NA
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    if out["timestamp"].isna().any():
        raise ValueError("Provider output has non-parseable timestamps")
    out = out[["timestamp", "symbol", *_BAR_COLUMNS]].sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    return out


def _long_to_symbol_map(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if frame.empty:
        return {}
    out: dict[str, pd.DataFrame] = {}
    for symbol, group in frame.groupby("symbol", sort=True):
        per_symbol = (
            group.drop(columns=["symbol"])
            .set_index("timestamp")
            .sort_index()
        )
        per_symbol.index = pd.DatetimeIndex(pd.to_datetime(per_symbol.index, utc=True))
        out[str(symbol)] = per_symbol
    return out


def fetch_multi_symbol(
    symbols: list[str],
    start: date | str,
    end: date | str,
    provider: str = "fmp",
    frequency: str = "1d",
    source: str = "openbb",
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """Fetch bars for multiple FX symbols as symbol -> OHLCV frame mapping."""
    engine = create_provider(source, openbb_provider=provider, seed=seed)
    if not engine.supports_frequency(frequency):
        raise ValueError(
            f"Configured provider '{source}' does not support bar frequency '{frequency}'."
        )
    long_df = engine.get_history(symbols=symbols, start=start, end=end, frequency=frequency)
    canonical = _canonicalize_long_history(long_df)
    return _long_to_symbol_map(canonical)


def fetch_fx_bars(
    symbol: str,
    start: date | str,
    end: date | str,
    provider: str = "fmp",
    frequency: str = "1d",
    source: str = "openbb",
    seed: int = 42,
) -> pd.DataFrame:
    """Fetch bars for one FX symbol as OHLCV frame indexed by UTC timestamp."""
    multi = fetch_multi_symbol(
        symbols=[symbol],
        start=start,
        end=end,
        provider=provider,
        frequency=frequency,
        source=source,
        seed=seed,
    )
    return multi.get(symbol, pd.DataFrame(columns=_BAR_COLUMNS))
