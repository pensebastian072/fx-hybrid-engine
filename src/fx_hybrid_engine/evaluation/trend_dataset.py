"""Trend dataset builder for versioned Stage 4 training."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fx_hybrid_engine.contracts import SCHEMA_VERSION
from fx_hybrid_engine.data.alignment import align_multi
from fx_hybrid_engine.data.provider import fetch_multi_symbol
from fx_hybrid_engine.engines.trend_features import (
    compute_trend_features,
    feature_columns,
    feature_schema_hash,
)
from fx_hybrid_engine.utils.config import load_config
from fx_hybrid_engine.utils.identity import hash_config, make_run_id, resolve_git_commit


def hash_dataset(df: pd.DataFrame) -> str:
    """Deterministic hash for a tabular dataset."""
    if df.empty:
        return hashlib.sha256(b"").hexdigest()
    hashed = pd.util.hash_pandas_object(df, index=True, categorize=False).values.tobytes()
    return hashlib.sha256(hashed).hexdigest()


def _feature_summary(df: pd.DataFrame, cols: list[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for col in cols:
        series = df[col]
        out[col] = {
            "mean": float(series.mean()),
            "std": float(series.std(ddof=0)),
            "min": float(series.min()),
            "max": float(series.max()),
        }
    return out


def build_trend_dataset(
    *,
    config_path: str | Path = "config/default.yaml",
    output_dir: str | Path | None = None,
    run_id: str | None = None,
    symbols: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    frequency: str | None = None,
) -> dict[str, object]:
    """Build reproducible trend dataset and write parquet + stats JSON."""
    cfg = load_config(config_path)
    selected_symbols = sorted(symbols or list(cfg.trend_symbols))
    if not selected_symbols:
        raise ValueError("No trend symbols configured for dataset build")

    start = start_date or cfg.walkforward.start_date
    end = end_date or cfg.walkforward.end_date
    freq = frequency or cfg.data.bar_frequency
    raw = fetch_multi_symbol(
        symbols=selected_symbols,
        start=start,
        end=end,
        provider=cfg.data.openbb_provider,
        frequency=freq,
        source=cfg.data.source,
        seed=cfg.robustness.random_seed,
    )
    aligned = align_multi(raw)
    if not aligned:
        raise RuntimeError("No aligned data available for trend dataset build")

    cols = feature_columns(cfg.trend)
    horizon = max(1, int(cfg.trend.label_horizon_bars))
    threshold = float(cfg.trend.label_threshold_bps) / 10_000.0
    frames: list[pd.DataFrame] = []
    for symbol in selected_symbols:
        df = aligned.get(symbol)
        if df is None or df.empty or "close" not in df.columns:
            continue
        feats = compute_trend_features(df["close"], cfg.trend)
        fwd_return = (df["close"].shift(-horizon) / df["close"]) - 1.0
        labels = (fwd_return > threshold).astype(int)
        frame = feats[cols].copy()
        frame["forward_return"] = fwd_return
        frame["label"] = labels
        frame["timestamp"] = pd.to_datetime(frame.index, utc=True)
        frame["symbol"] = symbol
        frame = frame[["timestamp", "symbol", *cols, "forward_return", "label"]]
        frame = frame.dropna()
        if frame.empty:
            continue
        frame["label"] = frame["label"].astype(int)
        frames.append(frame)

    if not frames:
        raise RuntimeError("Trend dataset is empty after feature/label filtering")
    dataset = pd.concat(frames, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(drop=True)

    now = datetime.now(UTC)
    cfg_payload = asdict(cfg)
    cfg_hash = hash_config(cfg_payload)
    effective_run_id = run_id or make_run_id(now, cfg_hash)
    run_root = Path(output_dir) if output_dir else Path("artifacts/trend_dataset") / effective_run_id
    run_root.mkdir(parents=True, exist_ok=True)

    dataset_path = run_root / "trend_dataset.parquet"
    stats_path = run_root / "trend_dataset_stats.json"
    dataset.to_parquet(dataset_path, index=False)

    class_counts = dataset["label"].value_counts().sort_index()
    class_balance = {str(int(k)): float(v) for k, v in (class_counts / max(1, len(dataset))).items()}
    missing_counts = {str(k): int(v) for k, v in dataset.isna().sum().items()}
    data_hash = hash_dataset(dataset)
    stats = {
        "run_id": effective_run_id,
        "created_at_utc": now.isoformat(),
        "config_path": str(Path(config_path).resolve()),
        "git_commit": resolve_git_commit(),
        "config_hash": cfg_hash,
        "schema_version": SCHEMA_VERSION,
        "feature_schema_hash": feature_schema_hash(cfg.trend),
        "symbols": selected_symbols,
        "bar_frequency": freq,
        "date_range": {"start": str(start), "end": str(end)},
        "rows": int(len(dataset)),
        "class_balance": class_balance,
        "missing_counts": missing_counts,
        "feature_summary": _feature_summary(dataset, cols),
        "label_mode": "binary",
        "label_horizon_bars": horizon,
        "label_threshold_bps": float(cfg.trend.label_threshold_bps),
        "data_hash": data_hash,
    }
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return {
        "run_dir": str(run_root),
        "dataset_path": str(dataset_path),
        "stats_path": str(stats_path),
        "data_hash": data_hash,
        "rows": int(len(dataset)),
    }

