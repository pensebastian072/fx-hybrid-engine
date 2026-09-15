"""Walk-forward training for versioned trend model artifacts."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from fx_hybrid_engine.contracts import SCHEMA_VERSION
from fx_hybrid_engine.engines.trend_features import feature_columns, feature_schema_hash
from fx_hybrid_engine.evaluation.trend_dataset import build_trend_dataset, hash_dataset
from fx_hybrid_engine.evaluation.walkforward import generate_walkforward_splits
from fx_hybrid_engine.ops.model_registry import register_model_version
from fx_hybrid_engine.utils.config import load_config
from fx_hybrid_engine.utils.identity import hash_config, make_run_id, resolve_git_commit


def _train_pipeline(
    X: np.ndarray,
    y: np.ndarray,
    *,
    random_seed: int,
    class_weight: str | None,
) -> Pipeline:
    clf = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    random_state=random_seed,
                    class_weight=class_weight,
                ),
            ),
        ]
    )
    clf.fit(X, y)
    return clf


def _safe_auc(y_true: np.ndarray, p_up: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        return float("nan")
    return float(roc_auc_score(y_true, p_up))


def train_trend_walkforward(
    *,
    config_path: str | Path = "config/default.yaml",
    model_version: str | None = None,
    dataset_path: str | Path | None = None,
    output_root: str | Path | None = None,
) -> dict[str, object]:
    """Train and persist versioned trend model artifacts with OOS split metrics."""
    cfg = load_config(config_path)
    cfg_payload = asdict(cfg)
    cfg_hash = hash_config(cfg_payload)
    now = datetime.now(UTC)
    resolved_version = model_version or make_run_id(now, cfg_hash)
    model_root = Path(output_root or cfg.trend.model_root)
    model_dir = model_root / resolved_version
    model_dir.mkdir(parents=True, exist_ok=True)

    if dataset_path is None:
        ds_meta = build_trend_dataset(
            config_path=config_path,
            output_dir=Path("artifacts/trend_dataset") / resolved_version,
            run_id=resolved_version,
        )
        ds_path = Path(str(ds_meta["dataset_path"]))
        data_hash = str(ds_meta["data_hash"])
    else:
        ds_path = Path(dataset_path)
        if not ds_path.exists():
            raise FileNotFoundError(f"Trend dataset path not found: {ds_path}")
        dataset = pd.read_parquet(ds_path)
        data_hash = hash_dataset(dataset)

    dataset = pd.read_parquet(ds_path)
    if dataset.empty:
        raise RuntimeError("Trend dataset is empty")
    dataset["timestamp"] = pd.to_datetime(dataset["timestamp"], utc=True)
    dataset = dataset.sort_values(["timestamp", "symbol"]).reset_index(drop=True)

    cols = feature_columns(cfg.trend)
    required_cols = {"timestamp", "symbol", "label", *cols}
    missing = required_cols.difference(set(dataset.columns))
    if missing:
        raise ValueError(f"Trend dataset missing required columns: {sorted(missing)}")

    class_weight = None if str(cfg.trend.class_weight).lower() in {"", "none", "null"} else cfg.trend.class_weight
    ts_index = pd.DatetimeIndex(sorted(dataset["timestamp"].unique()))
    split_specs = generate_walkforward_splits(
        ts_index,
        train_window_days=cfg.trend.train_window_days,
        test_window_days=cfg.trend.test_window_days,
        step_days=cfg.trend.step_days,
        max_splits=None,
    )
    if not split_specs:
        raise RuntimeError("No walk-forward splits available for trend training")

    rows: list[dict[str, object]] = []
    seed = int(cfg.robustness.random_seed)
    min_rows = int(cfg.trend.min_train_rows)
    for split in split_specs:
        train_idx = set(pd.DatetimeIndex(split["train_index"]).tolist())
        test_idx = set(pd.DatetimeIndex(split["test_index"]).tolist())
        train_df = dataset[dataset["timestamp"].isin(train_idx)]
        test_df = dataset[dataset["timestamp"].isin(test_idx)]
        if len(train_df) < min_rows or test_df.empty or train_df["label"].nunique() < 2:
            continue

        X_train = train_df[cols].to_numpy(dtype=float)
        y_train = train_df["label"].to_numpy(dtype=int)
        X_test = test_df[cols].to_numpy(dtype=float)
        y_test = test_df["label"].to_numpy(dtype=int)
        model = _train_pipeline(X_train, y_train, random_seed=seed, class_weight=class_weight)
        p_up = model.predict_proba(X_test)[:, 1]
        y_pred = (p_up >= float(cfg.trend.decision_threshold or cfg.trend.signal_threshold)).astype(int)
        row = {
            "split_idx": int(split["split_idx"]),
            "train_start": pd.Timestamp(split["train_start"]).isoformat(),
            "train_end": pd.Timestamp(split["train_end"]).isoformat(),
            "test_start": pd.Timestamp(split["test_start"]).isoformat(),
            "test_end": pd.Timestamp(split["test_end"]).isoformat(),
            "n_train_rows": int(len(train_df)),
            "n_test_rows": int(len(test_df)),
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
            "roc_auc": _safe_auc(y_test, p_up),
        }
        rows.append(row)

    metrics_df = pd.DataFrame(rows)
    if metrics_df.empty:
        raise RuntimeError("No valid trend training splits met minimum training requirements")

    X_full = dataset[cols].to_numpy(dtype=float)
    y_full = dataset["label"].to_numpy(dtype=int)
    if len(np.unique(y_full)) < 2:
        raise RuntimeError("Trend dataset labels have <2 classes; cannot train LogisticRegression")
    final_model = _train_pipeline(X_full, y_full, random_seed=seed, class_weight=class_weight)

    import joblib

    model_path = model_dir / "trend_model.joblib"
    joblib.dump(final_model, model_path)
    metrics_path = model_dir / "metrics_by_split.csv"
    metrics_df.to_csv(metrics_path, index=False)

    summary = {
        "model_version": resolved_version,
        "n_splits": int(metrics_df["split_idx"].nunique()),
        "median_accuracy": float(metrics_df["accuracy"].median()),
        "std_accuracy": float(metrics_df["accuracy"].std(ddof=0)),
        "median_f1": float(metrics_df["f1"].median()),
        "std_f1": float(metrics_df["f1"].std(ddof=0)),
        "median_roc_auc": float(metrics_df["roc_auc"].dropna().median()) if metrics_df["roc_auc"].notna().any() else float("nan"),
        "worst_split_by_f1": int(metrics_df.sort_values("f1").iloc[0]["split_idx"]),
    }
    summary_path = model_dir / "oos_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    metadata = {
        "model_version": resolved_version,
        "created_at_utc": now.isoformat(),
        "git_commit": resolve_git_commit(),
        "config_hash": cfg_hash,
        "schema_version": SCHEMA_VERSION,
        "feature_schema_hash": feature_schema_hash(cfg.trend),
        "feature_columns": cols,
        "label_mode": "binary",
        "label_horizon_bars": int(cfg.trend.label_horizon_bars),
        "label_threshold_bps": float(cfg.trend.label_threshold_bps),
        "train_window_days": int(cfg.trend.train_window_days),
        "test_window_days": int(cfg.trend.test_window_days),
        "step_days": int(cfg.trend.step_days),
        "seed": seed,
        "data_hash": data_hash,
        "symbols": sorted(dataset["symbol"].unique().tolist()),
        "bar_frequency": cfg.data.bar_frequency,
        "model_family": "logreg",
        "dataset_path": str(ds_path.resolve()),
        "decision_threshold": float(cfg.trend.decision_threshold or cfg.trend.signal_threshold),
    }
    metadata_path = model_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    register_model_version(
        cfg.model_registry,
        run_id=resolved_version,
        model_type="trend",
        model_version=resolved_version,
        training_window=f"{str(dataset['timestamp'].min())} -> {str(dataset['timestamp'].max())}",
        feature_schema_version=metadata["feature_schema_hash"],
        data_hash=data_hash,
        artifact_path=str(model_path.resolve()),
        created_at_utc=now.isoformat(),
    )

    return {
        "model_dir": str(model_dir),
        "model_path": str(model_path),
        "metadata_path": str(metadata_path),
        "metrics_path": str(metrics_path),
        "summary_path": str(summary_path),
        "model_version": resolved_version,
        "data_hash": data_hash,
    }

