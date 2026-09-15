"""HMM-based probabilistic regime engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

from fx_lean_engine.engines.regime import RegimeOrchestrator
from fx_lean_engine.types import FeatureVector, RegimeState

try:  # pragma: no cover - import guarded for environments without hmmlearn
    from hmmlearn.hmm import GaussianHMM  # type: ignore
except Exception:  # pragma: no cover
    GaussianHMM = None  # type: ignore


@dataclass(slots=True)
class RegimeEngineHMM:
    """HMM regime engine with deterministic state mapping."""

    symbols: list[str]
    lookback_bars: int = 8640
    retrain_frequency: str = "weekly"
    n_components: int = 3
    covariance_type: str = "full"
    n_iter: int = 200
    random_state: int = 42
    trend_prob_threshold: float = 0.6
    chop_prob_threshold: float = 0.6
    risk_off_prob_threshold: float = 0.6

    _observations: list[np.ndarray] = field(default_factory=list)
    _timestamps: list[datetime] = field(default_factory=list)
    _model: Any = None
    _last_train_ts: datetime | None = None
    _state_map: dict[int, str] = field(default_factory=dict)
    _last_label: str | None = None
    _pending_posteriors: list[dict[str, Any]] = field(default_factory=list)
    _pending_events: list[dict[str, Any]] = field(default_factory=list)
    _latest_params: dict[str, Any] | None = None
    _fallback: RegimeOrchestrator | None = None

    def __post_init__(self) -> None:
        self.symbols = [str(symbol).upper().strip() for symbol in self.symbols]
        self.lookback_bars = max(int(self.lookback_bars), 50)
        self.retrain_frequency = str(self.retrain_frequency).strip().lower()
        if self.retrain_frequency not in {"weekly", "daily"}:
            self.retrain_frequency = "weekly"
        self.n_components = max(int(self.n_components), 2)
        self.n_iter = max(int(self.n_iter), 20)
        self.random_state = int(self.random_state)
        self.trend_prob_threshold = min(max(float(self.trend_prob_threshold), 0.0), 1.0)
        self.chop_prob_threshold = min(max(float(self.chop_prob_threshold), 0.0), 1.0)
        self.risk_off_prob_threshold = min(max(float(self.risk_off_prob_threshold), 0.0), 1.0)
        self._fallback = RegimeOrchestrator(symbols=self.symbols)

    def _record_posterior(self, timestamp: datetime, p_trend: float, p_chop: float, p_risk_off: float, state: str, source: str) -> None:
        self._pending_posteriors.append(
            {
                "timestamp": timestamp.isoformat(),
                "p_trend": float(p_trend),
                "p_chop": float(p_chop),
                "p_risk_off": float(p_risk_off),
                "state": str(state),
                "source": source,
            }
        )

    @staticmethod
    def _utc_timestamp(timestamp: datetime | None) -> datetime:
        now = timestamp or datetime.now(tz=UTC)
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    @staticmethod
    def _feature_row(feature_snapshot: dict[str, FeatureVector]) -> np.ndarray | None:
        values: list[tuple[float, float, float]] = []
        for vector in feature_snapshot.values():
            values.append((float(vector.log_ret_1), float(vector.vol_20_pct), float(vector.range_pct)))
        if not values:
            return None
        arr = np.asarray(values, dtype=float)
        medians = np.median(arr, axis=0)
        if np.isnan(medians).any() or np.isinf(medians).any():
            return None
        return medians

    def _should_retrain(self, timestamp: datetime) -> bool:
        if self._model is None:
            return True
        if self._last_train_ts is None:
            return True
        if self.retrain_frequency == "daily":
            return timestamp.date() > self._last_train_ts.date()
        # weekly retrain at ISO week boundary
        return (timestamp.isocalendar().year, timestamp.isocalendar().week) != (
            self._last_train_ts.isocalendar().year,
            self._last_train_ts.isocalendar().week,
        )

    def _fit_model(self, timestamp: datetime) -> None:
        if GaussianHMM is None:
            return
        if len(self._observations) < self.lookback_bars:
            return

        train = np.asarray(self._observations[-self.lookback_bars :], dtype=float)
        if np.isnan(train).any() or np.isinf(train).any():
            return
        jitter = np.linspace(0.0, 1e-9, num=train.shape[0], dtype=float).reshape(-1, 1)
        train_stable = train + jitter

        model = GaussianHMM(
            n_components=self.n_components,
            covariance_type=self.covariance_type,
            n_iter=self.n_iter,
            random_state=self.random_state,
        )
        try:
            model.fit(train_stable)
            states = model.predict(train_stable)
        except Exception:
            # Fallback keeps HMM available when full-covariance fitting becomes singular.
            fallback_model = GaussianHMM(
                n_components=self.n_components,
                covariance_type="diag",
                n_iter=self.n_iter,
                random_state=self.random_state,
            )
            fallback_model.fit(train_stable)
            model = fallback_model
            states = model.predict(train_stable)

        mean_ret: dict[int, float] = {}
        mean_vol: dict[int, float] = {}
        for state in range(self.n_components):
            mask = states == state
            if not np.any(mask):
                mean_ret[state] = float("-inf")
                mean_vol[state] = float("-inf")
                continue
                mean_ret[state] = float(np.mean(train_stable[mask, 0]))
                mean_vol[state] = float(np.mean(train_stable[mask, 1]))

        trend_state = max(mean_ret, key=mean_ret.get)
        remaining = [state for state in range(self.n_components) if state != trend_state]
        if remaining:
            risk_off_state = max(remaining, key=lambda item: mean_vol.get(item, float("-inf")))
        else:
            risk_off_state = trend_state
        chop_candidates = [state for state in range(self.n_components) if state not in {trend_state, risk_off_state}]
        chop_state = chop_candidates[0] if chop_candidates else trend_state

        state_map = {state: "CHOP" for state in range(self.n_components)}
        state_map[trend_state] = "TREND"
        state_map[risk_off_state] = "RISK_OFF"
        state_map[chop_state] = "CHOP"

        self._model = model
        self._state_map = state_map
        self._last_train_ts = timestamp
        self._latest_params = {
            "trained_at": timestamp.isoformat(),
            "n_components": int(self.n_components),
            "covariance_type": str(getattr(model, "covariance_type", self.covariance_type)),
            "n_iter": int(self.n_iter),
            "random_state": int(self.random_state),
            "means": np.asarray(model.means_).tolist(),
            "covars": np.asarray(model.covars_).tolist(),
            "transmat": np.asarray(model.transmat_).tolist(),
            "startprob": np.asarray(model.startprob_).tolist(),
        }

    def _weights(self, p_trend: float, p_chop: float, p_risk_off: float) -> tuple[str, float, float]:
        if p_risk_off > self.risk_off_prob_threshold:
            return "RISK_OFF", 0.0, 0.0
        if p_trend > self.trend_prob_threshold:
            return "TREND", 0.8, 0.2
        if p_chop > self.chop_prob_threshold:
            return "CHOP", 0.2, 0.8

        blend_total = max(p_trend + p_chop, 1e-12)
        blend_trend = p_trend / blend_total
        blend_pairs = p_chop / blend_total
        trend_weight = 0.2 + 0.6 * blend_trend
        pairs_weight = 0.2 + 0.6 * blend_pairs
        state = "TREND" if p_trend >= p_chop else "CHOP"
        return state, float(trend_weight), float(pairs_weight)

    def update(
        self,
        close_snapshot: dict[str, float],
        feature_snapshot: dict[str, FeatureVector] | None = None,
        timestamp: datetime | None = None,
    ) -> RegimeState:
        """Update HMM state and emit probabilistic regime output."""
        ts = self._utc_timestamp(timestamp)

        if feature_snapshot is None:
            fallback = self._fallback.update(close_snapshot, feature_snapshot=None, timestamp=ts)
            self._record_posterior(ts, fallback.p_trend, fallback.p_chop, fallback.p_risk_off, fallback.state, "fallback")
            return fallback

        row = self._feature_row(feature_snapshot)
        if row is None:
            fallback = self._fallback.update(close_snapshot, feature_snapshot=None, timestamp=ts)
            self._record_posterior(ts, fallback.p_trend, fallback.p_chop, fallback.p_risk_off, fallback.state, "fallback")
            return fallback

        self._observations.append(row)
        self._timestamps.append(ts)

        if self._should_retrain(ts):
            self._fit_model(ts)

        if self._model is None or not self._state_map:
            fallback = self._fallback.update(close_snapshot, feature_snapshot=None, timestamp=ts)
            self._record_posterior(ts, fallback.p_trend, fallback.p_chop, fallback.p_risk_off, fallback.state, "fallback")
            return fallback

        obs = row.reshape(1, -1)
        probs = np.asarray(self._model.predict_proba(obs)[0], dtype=float)
        p_trend = float(sum(probs[state] for state, label in self._state_map.items() if label == "TREND"))
        p_chop = float(sum(probs[state] for state, label in self._state_map.items() if label == "CHOP"))
        p_risk_off = float(sum(probs[state] for state, label in self._state_map.items() if label == "RISK_OFF"))

        state, trend_weight, pairs_weight = self._weights(p_trend, p_chop, p_risk_off)
        self._record_posterior(ts, p_trend, p_chop, p_risk_off, state, "hmm")

        if self._last_label is not None and self._last_label != state:
            self._pending_events.append(
                {
                    "timestamp": ts.isoformat(),
                    "event_type": "REGIME_TRANSITION",
                    "from_state": self._last_label,
                    "to_state": state,
                    "p_trend": p_trend,
                    "p_chop": p_chop,
                    "p_risk_off": p_risk_off,
                }
            )
        self._last_label = state

        return RegimeState(
            state=state,
            p_trend=float(p_trend),
            p_chop=float(p_chop),
            p_risk_off=float(p_risk_off),
            trend_weight=float(trend_weight),
            pairs_weight=float(pairs_weight),
        )

    def drain_artifacts(self) -> dict[str, Any]:
        """Return and clear per-bar HMM artifact payloads."""
        payload = {
            "regime_posteriors": list(self._pending_posteriors),
            "regime_events": list(self._pending_events),
            "regime_hmm_params": dict(self._latest_params) if self._latest_params is not None else None,
            "regime_state_map": {str(key): value for key, value in self._state_map.items()} if self._state_map else None,
        }
        self._pending_posteriors.clear()
        self._pending_events.clear()
        return payload
