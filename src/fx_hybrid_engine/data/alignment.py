"""Bar alignment utilities: UTC normalization, consolidation, and health diagnostics."""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("fxhe.data.alignment")

_BAR_COLS = ("open", "high", "low", "close")


def _freq_alias(bar_frequency: str) -> str:
    mapping = {"15m": "15min", "1h": "1h", "1d": "1D"}
    key = str(bar_frequency).lower()
    if key not in mapping:
        raise ValueError(f"Unsupported bar frequency '{bar_frequency}'")
    return mapping[key]


def normalize_to_utc(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure index is UTC timezone-aware datetime index."""
    if df.index.tz is None:
        out = df.copy()
        out.index = out.index.tz_localize("UTC")
        return out
    if str(df.index.tz) != "UTC":
        out = df.copy()
        out.index = out.index.tz_convert("UTC")
        return out
    return df


def detect_gaps(df: pd.DataFrame, expected_frequency: str) -> list[pd.Timestamp]:
    """Detect missing timestamps for expected cadence."""
    if len(df.index) < 2:
        return []
    freq = _freq_alias(expected_frequency)
    expected = pd.date_range(start=df.index[0], end=df.index[-1], freq=freq, tz=df.index.tz)
    missing = expected.difference(df.index)
    return list(missing)


def forward_fill(df: pd.DataFrame, max_fill: int = 1) -> pd.DataFrame:
    """Forward-fill missing bars up to max_fill consecutive bars."""
    if len(df) < 2:
        return df
    freq = pd.infer_freq(df.index)
    if freq is None:
        return df
    full_index = pd.date_range(start=df.index[0], end=df.index[-1], freq=freq, tz=df.index.tz)
    out = df.reindex(full_index)
    return out.ffill(limit=max_fill)


def normalize_and_consolidate(
    df: pd.DataFrame,
    *,
    symbol: str,
    target_frequency: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Normalize one symbol frame to canonical bar schema and cadence."""
    if df.empty:
        return df.copy(), {
            "symbol": symbol,
            "target_frequency": target_frequency,
            "rows_input": 0,
            "rows_output": 0,
            "duplicates_removed": 0,
            "non_monotonic_fixed": False,
            "gap_count": 0,
            "status": "empty",
        }

    out = df.copy()
    if "timestamp" in out.columns:
        out = out.set_index("timestamp")
    out.index = pd.to_datetime(out.index, utc=True, errors="coerce")
    out = out[~out.index.isna()]

    for col in _BAR_COLS:
        if col not in out.columns:
            raise ValueError(f"Missing required bar column '{col}' for symbol {symbol}")
    if "volume" not in out.columns:
        out["volume"] = pd.NA

    rows_input = int(len(out))
    non_monotonic = not out.index.is_monotonic_increasing
    out = normalize_to_utc(out)
    out = out.sort_index()

    duplicates_removed = int(out.index.duplicated(keep="last").sum())
    if duplicates_removed:
        out = out[~out.index.duplicated(keep="last")]

    target = _freq_alias(target_frequency)
    inferred = pd.infer_freq(out.index)
    if inferred is not None and inferred != target:
        # Consolidate to configured cadence.
        out = (
            out.resample(target)
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna(subset=["open", "high", "low", "close"])
        )

    gaps = detect_gaps(out, expected_frequency=target_frequency) if len(out) >= 2 else []
    health = {
        "symbol": symbol,
        "target_frequency": target_frequency,
        "rows_input": rows_input,
        "rows_output": int(len(out)),
        "duplicates_removed": duplicates_removed,
        "non_monotonic_fixed": bool(non_monotonic),
        "gap_count": int(len(gaps)),
        "status": "ok",
    }
    return out[["open", "high", "low", "close", "volume"]], health


def align_multi(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Align multiple symbol DataFrames to a common UTC index (inner join)."""
    if not data:
        return {}
    normed = {sym: normalize_to_utc(df) for sym, df in data.items()}
    common = None
    for df in normed.values():
        common = df.index if common is None else common.intersection(df.index)
    return {sym: df.loc[common] for sym, df in normed.items()}


def normalize_universe(
    data: dict[str, pd.DataFrame],
    *,
    target_frequency: str,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Normalize all symbols and return aligned bars with health diagnostics."""
    normalized: dict[str, pd.DataFrame] = {}
    health_rows: list[dict[str, object]] = []
    for symbol, frame in data.items():
        norm, health = normalize_and_consolidate(frame, symbol=symbol, target_frequency=target_frequency)
        normalized[symbol] = norm
        health_rows.append(health)
    return align_multi(normalized), pd.DataFrame(health_rows)
