"""ML ensemble signal engine: RandomForest + XGBoost classifier.

Generates directional (LONG/SHORT/FLAT) signals using an ensemble of tree-based
classifiers trained on combined basic + advanced technical features.

Design adapted from:
- stefan-jansen/machine-learning-for-trading ch11 (Decision Trees / Random Forests)
  and ch12 (Gradient Boosting / XGBoost)
- cwu392/Machine-Learning-for-Trading strategy learner/StrategyLearner.py
  (BagLearner over DTLearner pattern → translated here to scikit-learn RF + XGBoost)

Key differences from TrendEngine:
- Uses extended feature set (basic indicators + advanced: Bollinger, MACD, ATR, etc.)
- Stacks RF and XGBoost predictions via soft-voting ensemble
- Supports versioned model artifacts compatible with the existing models/trend/ pattern
- Gracefully falls back to RF-only when xgboost is not installed
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from fx_hybrid_engine.engines.types import Direction, EngineOutput, EngineType, Signal
from fx_hybrid_engine.features.indicators import compute_all
from fx_hybrid_engine.utils.config import MLSignalConfig

logger = logging.getLogger("fxhe.engines.ml_signal")

_FEATURE_COLS_BASIC = [
    "log_return",
    "sma_fast",
    "sma_slow",
    "ema_fast",
    "rsi",
    "realized_vol",
    "momentum_slope",
    "sma_crossover",
]

_FEATURE_COLS_ADVANCED = [
    "bb_pct_b",
    "bb_bandwidth",
    "macd_line",
    "macd_signal",
    "macd_histogram",
]


def _feature_columns(config: MLSignalConfig) -> list[str]:
    cols = list(_FEATURE_COLS_BASIC)
    if config.use_advanced_features:
        cols.extend(_FEATURE_COLS_ADVANCED)
    return cols


def _compute_features(close: pd.Series, config: MLSignalConfig) -> pd.DataFrame:
    """Return a DataFrame of all model features aligned to close.index."""
    from fx_hybrid_engine.features.advanced import bollinger_bands, macd  # noqa: PLC0415

    basic = compute_all(
        close,
        sma_fast=config.macd_fast * 4,   # ~50
        sma_slow=config.macd_slow * 8,   # ~200 (reuse macd params as proxy)
    )
    if not config.use_advanced_features:
        return basic
    bb = bollinger_bands(close, window=config.bb_window)
    mc = macd(close, fast=config.macd_fast, slow=config.macd_slow)
    return pd.concat([basic, bb[["bb_pct_b", "bb_bandwidth"]], mc], axis=1)


class MLSignalEngine:
    """RandomForest + XGBoost ensemble directional signal engine.

    Usage
    -----
    >>> engine = MLSignalEngine(config)
    >>> engine.train({"EURUSD": df_eurusd, "GBPUSD": df_gbpusd})
    >>> output = engine.generate(data, timestamp)

    The ``generate`` method produces ``EngineOutput(engine=EngineType.ML_ENSEMBLE, ...)``
    with Signal objects that have ``confidence`` = the winning class probability.
    """

    def __init__(self, config: MLSignalConfig) -> None:
        self.config = config
        self._ensemble: object | None = None   # VotingClassifier
        self._model_version: str | None = None
        self._metadata: dict[str, object] = {}

    @property
    def feature_columns(self) -> list[str]:
        return _feature_columns(self.config)

    @property
    def is_fitted(self) -> bool:
        return self._ensemble is not None

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _build_estimators(self) -> list[tuple[str, object]]:
        from sklearn.ensemble import RandomForestClassifier  # noqa: PLC0415

        rf = RandomForestClassifier(
            n_estimators=self.config.n_estimators,
            max_depth=self.config.max_depth,
            class_weight=self.config.class_weight if self.config.class_weight != "none" else None,
            random_state=self.config.seed,
            n_jobs=-1,
        )
        estimators = [("rf", rf)]

        if self.config.use_xgboost:
            try:
                from xgboost import XGBClassifier  # noqa: PLC0415

                xgb = XGBClassifier(
                    n_estimators=self.config.n_estimators,
                    max_depth=self.config.max_depth,
                    use_label_encoder=False,
                    eval_metric="logloss",
                    random_state=self.config.seed,
                    verbosity=0,
                )
                estimators.append(("xgb", xgb))
                logger.info("XGBoost included in ML ensemble")
            except ImportError:
                logger.warning("xgboost not installed — using RF-only ensemble")

        return estimators

    def train(self, data: dict[str, pd.DataFrame]) -> None:
        """Train ensemble on data dict {symbol: OHLCV DataFrame with 'close' column}."""
        from sklearn.ensemble import VotingClassifier  # noqa: PLC0415
        from sklearn.pipeline import Pipeline  # noqa: PLC0415
        from sklearn.preprocessing import StandardScaler  # noqa: PLC0415

        X_all: list[np.ndarray] = []
        y_all: list[np.ndarray] = []
        cols = self.feature_columns
        horizon = max(1, int(self.config.label_horizon_bars))
        threshold = float(self.config.label_threshold_bps) / 10_000.0

        for sym, df in data.items():
            if "close" not in df.columns or len(df) < self.config.min_train_rows:
                logger.warning("Skipping %s: insufficient data (%d rows)", sym, len(df))
                continue
            feats = _compute_features(df["close"], self.config)
            fwd_return = (df["close"].shift(-horizon) / df["close"]) - 1.0
            # 3-class label: 0=down, 1=flat, 2=up
            label = pd.cut(
                fwd_return,
                bins=[-np.inf, -threshold, threshold, np.inf],
                labels=[0, 1, 2],
            ).astype(float)
            available = [c for c in cols if c in feats.columns]
            if len(available) < len(cols):
                logger.warning("Missing features for %s: %s", sym, set(cols) - set(available))
            joined = feats[available].join(label.rename("label")).dropna()
            if joined.empty or joined["label"].nunique() < 2:
                logger.warning("Insufficient label diversity for %s — skipping", sym)
                continue
            X_all.append(joined[available].to_numpy(dtype=float))
            y_all.append(joined["label"].to_numpy(dtype=int))

        if not X_all:
            raise ValueError("No usable training data for MLSignalEngine")

        X = np.vstack(X_all)
        y = np.concatenate(y_all)

        estimators = self._build_estimators()
        if len(estimators) == 1:
            base = estimators[0][1]
        else:
            base = VotingClassifier(estimators=estimators, voting="soft", n_jobs=-1)

        pipe = Pipeline([("scaler", StandardScaler()), ("clf", base)])
        pipe.fit(X, y)

        self._ensemble = pipe
        self._model_version = "in_memory"
        self._metadata = {
            "model_version": "in_memory",
            "model_family": "ml_ensemble",
            "feature_columns": self.feature_columns,
            "label_horizon_bars": horizon,
            "label_threshold_bps": float(self.config.label_threshold_bps),
            "n_estimators": self.config.n_estimators,
            "use_xgboost": self.config.use_xgboost,
            "n_train_samples": len(y),
        }
        logger.info(
            "MLSignalEngine trained on %d samples (%d symbols)",
            len(y),
            len(data),
        )

    # ------------------------------------------------------------------
    # Save / Load
    # ------------------------------------------------------------------

    def save(self, version_dir: str | Path | None = None) -> Path:
        """Save model + metadata to a versioned directory."""
        if self._ensemble is None:
            raise RuntimeError("Engine has not been trained")
        import joblib  # noqa: PLC0415

        if version_dir is None:
            import datetime  # noqa: PLC0415

            version = datetime.datetime.utcnow().strftime("v%Y%m%d_%H%M%S")
            out_dir = Path(self.config.model_root) / version
        else:
            out_dir = Path(version_dir)

        out_dir.mkdir(parents=True, exist_ok=True)
        model_path = out_dir / "ml_signal_model.joblib"
        meta_path = out_dir / "metadata.json"

        joblib.dump(self._ensemble, model_path)
        self._metadata["model_version"] = out_dir.name
        meta_path.write_text(json.dumps(self._metadata, indent=2), encoding="utf-8")
        logger.info("MLSignalEngine saved to %s", out_dir)
        return out_dir

    def load(self, version_dir: str | Path | None = None) -> bool:
        """Load a saved model.  Returns True on success."""
        import joblib  # noqa: PLC0415

        if version_dir is None:
            root = Path(self.config.model_root)
            version = (self.config.model_version or "latest").strip()
            if version == "latest":
                if not root.exists():
                    logger.warning("ML ensemble model root not found: %s", root)
                    return False
                candidates = sorted(
                    [p for p in root.iterdir() if p.is_dir() and (p / "metadata.json").exists()]
                )
                if not candidates:
                    logger.warning("No versioned ML ensemble model under %s", root)
                    return False
                dir_ = candidates[-1]
            else:
                dir_ = root / version
        else:
            dir_ = Path(version_dir)

        model_path = dir_ / "ml_signal_model.joblib"
        meta_path = dir_ / "metadata.json"
        if not model_path.exists():
            logger.warning("ML ensemble model not found: %s", model_path)
            return False

        self._ensemble = joblib.load(model_path)
        self._model_version = dir_.name
        if meta_path.exists():
            self._metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        logger.info("MLSignalEngine loaded from %s", dir_)
        return True

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def _predict(self, fvec: np.ndarray) -> tuple[Direction, float]:
        """Return (direction, confidence) from a (1, n_features) array."""
        proba = self._ensemble.predict_proba(fvec)[0]  # type: ignore[union-attr]
        # Classes: 0=down, 1=flat, 2=up
        p_down, p_flat, p_up = float(proba[0]), float(proba[1]), float(proba[2])
        threshold = float(self.config.decision_threshold)
        if p_up >= threshold and p_up >= p_down:
            return Direction.LONG, p_up
        if p_down >= threshold and p_down >= p_up:
            return Direction.SHORT, p_down
        return Direction.FLAT, p_flat

    def generate(self, data: dict[str, pd.DataFrame], timestamp: pd.Timestamp) -> EngineOutput:
        """Generate ML ensemble signals for each symbol in data."""
        output = EngineOutput(engine=EngineType.ML_ENSEMBLE, timestamp=timestamp)

        if self._ensemble is None:
            logger.warning("MLSignalEngine not trained — emitting FLAT for all symbols")
            for sym in data:
                output.signals.append(Signal(sym, Direction.FLAT, 0.0, EngineType.ML_ENSEMBLE, timestamp))
            return output

        cols = self.feature_columns
        for sym, df in data.items():
            if "close" not in df.columns or len(df) < 30:
                output.signals.append(Signal(sym, Direction.FLAT, 0.0, EngineType.ML_ENSEMBLE, timestamp))
                continue
            feats = _compute_features(df["close"], self.config)
            available = [c for c in cols if c in feats.columns]
            row = feats[available].iloc[-1]
            if row.isna().any() or len(available) < len(cols):
                output.signals.append(Signal(sym, Direction.FLAT, 0.0, EngineType.ML_ENSEMBLE, timestamp))
                continue
            fvec = row.to_numpy(dtype=float).reshape(1, -1)
            direction, confidence = self._predict(fvec)
            size = 1.0 if direction != Direction.FLAT else 0.0
            output.signals.append(
                Signal(
                    sym,
                    direction,
                    size,
                    EngineType.ML_ENSEMBLE,
                    timestamp,
                    confidence=confidence,
                    metadata={
                        "model_version": self._model_version or "unknown",
                        "decision_threshold": self.config.decision_threshold,
                    },
                )
            )
        return output
