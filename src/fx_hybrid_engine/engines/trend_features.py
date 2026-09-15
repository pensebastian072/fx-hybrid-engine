"""Canonical trend feature contract shared by training and live inference."""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from fx_hybrid_engine.features.indicators import compute_all
from fx_hybrid_engine.utils.config import TrendConfig


def feature_columns(_cfg: TrendConfig | None = None) -> list[str]:
    """Feature columns used by the trend classifier."""
    return [
        "log_return",
        "sma_crossover",
        "rsi",
        "realized_vol",
        "momentum_slope",
    ]


def compute_trend_features(close: pd.Series, cfg: TrendConfig) -> pd.DataFrame:
    """Compute the canonical trend feature frame from close prices."""
    return compute_all(
        close,
        sma_fast=cfg.sma_fast,
        sma_slow=cfg.sma_slow,
        mom_window=cfg.feature_lookback,
        vol_window=cfg.feature_lookback,
    )


def feature_schema_payload(cfg: TrendConfig) -> dict[str, object]:
    """Deterministic payload describing trend feature schema and lookbacks."""
    return {
        "feature_columns": feature_columns(cfg),
        "lookbacks": {
            "feature_lookback": int(cfg.feature_lookback),
            "sma_fast": int(cfg.sma_fast),
            "sma_slow": int(cfg.sma_slow),
        },
        "version": "trend_features_v1",
    }


def feature_schema_hash(cfg: TrendConfig) -> str:
    """Return sha256 hash of the canonical feature schema payload."""
    blob = json.dumps(feature_schema_payload(cfg), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()

