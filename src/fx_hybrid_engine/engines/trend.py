"""Trend (momentum) engine: LogisticRegression with MA-crossover fallback."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from fx_hybrid_engine.engines.trend_features import (
    compute_trend_features,
    feature_columns,
    feature_schema_hash,
)
from fx_hybrid_engine.engines.types import Direction, EngineOutput, EngineType, Signal
from fx_hybrid_engine.utils.config import TrendConfig

logger = logging.getLogger("fxhe.engines.trend")

MODEL_METADATA_REQUIRED_KEYS = (
    "model_version",
    "created_at_utc",
    "git_commit",
    "config_hash",
    "schema_version",
    "feature_schema_hash",
    "feature_columns",
    "label_mode",
    "label_horizon_bars",
    "label_threshold_bps",
    "train_window_days",
    "test_window_days",
    "step_days",
    "seed",
    "data_hash",
    "symbols",
    "bar_frequency",
    "model_family",
)


class TrendEngine:
    """Generates directional signals via a trained LogisticRegression model."""

    def __init__(self, config: TrendConfig) -> None:
        self.config = config
        self._model = None
        self._model_version: str | None = None
        self._model_metadata: dict[str, object] = {}

    @property
    def decision_threshold(self) -> float:
        if self.config.decision_threshold is not None:
            return float(self.config.decision_threshold)
        return float(self.config.signal_threshold)

    @property
    def model_version(self) -> str | None:
        return self._model_version

    @property
    def model_metadata(self) -> dict[str, object]:
        return dict(self._model_metadata)

    @property
    def feature_schema_hash(self) -> str:
        return feature_schema_hash(self.config)

    # ------------------------------------------------------------------
    # Model loading / saving
    # ------------------------------------------------------------------

    def load_model(self, path: str | Path | None = None) -> bool:
        """Load legacy serialized model path. Returns True on success."""
        model_path = Path(path or self.config.model_path)
        if not model_path.exists():
            logger.warning("Trend model not found at %s — using MA crossover fallback", model_path)
            return False
        try:
            import joblib  # noqa: PLC0415

            self._model = joblib.load(model_path)
            self._model_version = "legacy_path"
            self._model_metadata = {
                "model_version": self._model_version,
                "feature_schema_hash": self.feature_schema_hash,
                "feature_columns": feature_columns(self.config),
            }
            logger.info("Trend model loaded from %s", model_path)
            return True
        except Exception:
            logger.exception("Failed to load trend model from %s", model_path)
            return False

    def _resolve_model_version_dir(
        self,
        model_root: str | Path | None = None,
        model_version: str | None = None,
    ) -> tuple[str, Path]:
        root = Path(model_root or self.config.model_root)
        version = (model_version or self.config.model_version or "latest").strip()
        if version == "latest":
            if not root.exists():
                raise FileNotFoundError(f"Trend model root does not exist: {root}")
            candidates = sorted([p for p in root.iterdir() if p.is_dir() and (p / "metadata.json").exists()])
            if not candidates:
                raise FileNotFoundError(f"No versioned trend model found under {root}")
            resolved_dir = candidates[-1]
            return resolved_dir.name, resolved_dir
        resolved = root / version
        if not resolved.exists():
            raise FileNotFoundError(f"Requested trend model version '{version}' not found under {root}")
        return version, resolved

    def load_model_version(
        self,
        model_root: str | Path | None = None,
        model_version: str | None = None,
    ) -> bool:
        """Load versioned model artifact and validate schema metadata."""
        version, version_dir = self._resolve_model_version_dir(model_root=model_root, model_version=model_version)
        metadata_path = version_dir / "metadata.json"
        model_path = version_dir / "trend_model.joblib"

        if not metadata_path.exists():
            raise FileNotFoundError(f"Missing trend metadata: {metadata_path}")
        if not model_path.exists():
            raise FileNotFoundError(f"Missing trend model artifact: {model_path}")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        missing = [k for k in MODEL_METADATA_REQUIRED_KEYS if k not in metadata]
        if missing:
            raise ValueError(f"Invalid trend metadata; missing keys: {missing}")

        current_hash = self.feature_schema_hash
        artifact_hash = str(metadata.get("feature_schema_hash", ""))
        if artifact_hash != current_hash:
            raise ValueError(
                "Trend model feature schema mismatch: "
                f"artifact={artifact_hash}, current={current_hash}"
            )
        artifact_cols = [str(c) for c in metadata.get("feature_columns", [])]
        if artifact_cols != feature_columns(self.config):
            raise ValueError(
                "Trend model feature column mismatch: "
                f"artifact={artifact_cols}, current={feature_columns(self.config)}"
            )

        import joblib  # noqa: PLC0415

        self._model = joblib.load(model_path)
        self._model_version = version
        self._model_metadata = metadata
        logger.info("Trend model version '%s' loaded from %s", version, version_dir)
        return True

    def save_model(self, path: str | Path | None = None) -> None:
        """Serialize the trained model to disk (legacy path)."""
        if self._model is None:
            raise RuntimeError("No model to save")
        import joblib  # noqa: PLC0415

        out = Path(path or self.config.model_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, out)
        logger.info("Trend model saved to %s", out)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, data: dict[str, pd.DataFrame]) -> None:
        """Train LogisticRegression on canonical trend features and binary labels."""
        from sklearn.linear_model import LogisticRegression  # noqa: PLC0415
        from sklearn.pipeline import Pipeline  # noqa: PLC0415
        from sklearn.preprocessing import StandardScaler  # noqa: PLC0415

        X_all: list[np.ndarray] = []
        y_all: list[np.ndarray] = []
        horizon = max(1, int(self.config.label_horizon_bars))
        threshold = float(self.config.label_threshold_bps) / 10_000.0
        cols = feature_columns(self.config)
        required = self.config.sma_slow + self.config.feature_lookback + 10

        for sym, df in data.items():
            if "close" not in df.columns or len(df) < required:
                logger.warning("Not enough data for %s — skipping in trend training", sym)
                continue
            feats = compute_trend_features(df["close"], self.config)
            fwd_return = (df["close"].shift(-horizon) / df["close"]) - 1.0
            label = (fwd_return > threshold).astype(int)
            valid = feats[cols].join(label.rename("label")).dropna()
            if valid.empty or valid["label"].nunique() < 2:
                logger.warning("Insufficient label diversity for %s — skipping", sym)
                continue
            X_all.append(valid[cols].to_numpy(dtype=float))
            y_all.append(valid["label"].to_numpy(dtype=int))

        if not X_all:
            raise ValueError("No training data available for trend engine")

        class_weight = None if str(self.config.class_weight).lower() in {"", "none", "null"} else self.config.class_weight
        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        pipe = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(max_iter=1000, random_state=42, class_weight=class_weight)),
            ]
        )
        pipe.fit(X, y)
        self._model = pipe
        self._model_version = "in_memory"
        self._model_metadata = {
            "model_version": self._model_version,
            "feature_schema_hash": self.feature_schema_hash,
            "feature_columns": cols,
            "label_mode": "binary",
            "label_horizon_bars": horizon,
            "label_threshold_bps": float(self.config.label_threshold_bps),
            "model_family": "logreg",
            "decision_threshold": self.decision_threshold,
        }
        logger.info("Trend model trained on %d samples", len(y))

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def _feature_vector(self, df: pd.DataFrame) -> np.ndarray | None:
        """Extract latest feature row from close price history."""
        if "close" not in df.columns or len(df) < self.config.sma_slow:
            return None
        feats = compute_trend_features(df["close"], self.config)
        cols = feature_columns(self.config)
        row = feats[cols].iloc[-1]
        if row.isna().any():
            return None
        return row.to_numpy(dtype=float).reshape(1, -1)

    def _ma_crossover_signal(self, df: pd.DataFrame) -> Direction:
        """Fallback rule: long if fast SMA > slow SMA, else short."""
        from fx_hybrid_engine.features.indicators import sma  # noqa: PLC0415

        close = df["close"]
        if len(close) < self.config.sma_slow:
            return Direction.FLAT
        fast = sma(close, self.config.sma_fast).iloc[-1]
        slow = sma(close, self.config.sma_slow).iloc[-1]
        if pd.isna(fast) or pd.isna(slow):
            return Direction.FLAT
        return Direction.LONG if fast > slow else Direction.SHORT

    def _signal_metadata(self, p_down: float, p_up: float) -> dict[str, object]:
        return {
            "p_up": float(p_up),
            "p_down": float(p_down),
            "decision_threshold": float(self.decision_threshold),
            "model_version": self._model_version or "unknown",
        }

    def generate(self, data: dict[str, pd.DataFrame], timestamp: pd.Timestamp) -> EngineOutput:
        """Generate trend signals for all configured symbols."""
        output = EngineOutput(engine=EngineType.TREND, timestamp=timestamp)

        for sym, df in data.items():
            if self._model is not None:
                fvec = self._feature_vector(df)
                if fvec is None:
                    output.signals.append(Signal(sym, Direction.FLAT, 0.0, EngineType.TREND, timestamp))
                    continue
                proba = self._model.predict_proba(fvec)[0]  # [P(down), P(up)]
                p_up = float(proba[1])
                p_down = float(proba[0])
                meta = self._signal_metadata(p_down=p_down, p_up=p_up)
                if p_up >= self.decision_threshold:
                    output.signals.append(Signal(sym, Direction.LONG, 1.0, EngineType.TREND, timestamp, confidence=p_up, metadata=meta))
                elif p_down >= self.decision_threshold:
                    output.signals.append(Signal(sym, Direction.SHORT, 1.0, EngineType.TREND, timestamp, confidence=p_down, metadata=meta))
                else:
                    output.signals.append(Signal(sym, Direction.FLAT, 0.0, EngineType.TREND, timestamp, confidence=max(p_up, p_down), metadata=meta))
            else:
                direction = self._ma_crossover_signal(df)
                size = 1.0 if direction != Direction.FLAT else 0.0
                output.signals.append(Signal(sym, direction, size, EngineType.TREND, timestamp))

        return output

    def generate_from_features_row(
        self,
        symbol: str,
        features_row: pd.Series | dict[str, float] | None,
        timestamp: pd.Timestamp,
    ) -> Signal:
        """Generate a single-symbol signal from precomputed feature values."""
        if features_row is None:
            return Signal(symbol, Direction.FLAT, 0.0, EngineType.TREND, timestamp)

        row = features_row if isinstance(features_row, dict) else features_row.to_dict()

        if self._model is not None:
            cols = feature_columns(self.config)
            vals = [row.get(c) for c in cols]
            if any(pd.isna(v) for v in vals):
                return Signal(symbol, Direction.FLAT, 0.0, EngineType.TREND, timestamp)
            proba = self._model.predict_proba(np.asarray(vals, dtype=float).reshape(1, -1))[0]
            p_up = float(proba[1])
            p_down = float(proba[0])
            meta = self._signal_metadata(p_down=p_down, p_up=p_up)
            if p_up >= self.decision_threshold:
                return Signal(symbol, Direction.LONG, 1.0, EngineType.TREND, timestamp, confidence=p_up, metadata=meta)
            if p_down >= self.decision_threshold:
                return Signal(symbol, Direction.SHORT, 1.0, EngineType.TREND, timestamp, confidence=p_down, metadata=meta)
            return Signal(symbol, Direction.FLAT, 0.0, EngineType.TREND, timestamp, confidence=max(p_up, p_down), metadata=meta)

        fast = row.get("sma_fast")
        slow = row.get("sma_slow")
        if pd.isna(fast) or pd.isna(slow):
            return Signal(symbol, Direction.FLAT, 0.0, EngineType.TREND, timestamp)
        direction = Direction.LONG if float(fast) > float(slow) else Direction.SHORT
        return Signal(symbol, direction, 1.0, EngineType.TREND, timestamp)
