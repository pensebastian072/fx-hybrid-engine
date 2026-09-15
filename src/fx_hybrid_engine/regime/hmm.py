"""HMM regime model: GaussianHMM trainer and state inference."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("fxhe.regime.hmm")

# Canonical state name constants
TREND = "TREND"
CHOP = "CHOP"
RISK_OFF = "RISK_OFF"


class RegimeHMM:
    """Wraps hmmlearn GaussianHMM for 3-state market regime detection.

    Observation vector per bar: [realized_vol, momentum_score]
    - realized_vol: rolling annualized std of log returns
    - momentum_score: rolling mean of normalized price momentum slope

    States are labeled after training by ordering hidden states on mean realized_vol:
      lowest vol → TREND, middle → CHOP, highest vol → RISK_OFF.
    """

    def __init__(self, n_states: int = 3) -> None:
        self.n_states = n_states
        self._hmm = None
        self._state_map: dict[int, str] = {}  # hidden_state_idx → label
        self._state_order: list[int] = []

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, observations: np.ndarray) -> None:
        """Fit the GaussianHMM on an (N, 2) observation matrix.

        Parameters
        ----------
        observations:
            Array of shape (N, 2) where columns are [realized_vol, momentum_score].
        """
        try:
            from hmmlearn.hmm import GaussianHMM  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError("hmmlearn is required: pip install hmmlearn") from exc

        hmm = GaussianHMM(
            n_components=self.n_states,
            covariance_type="full",
            n_iter=200,
            random_state=42,
            verbose=False,
        )
        hmm.fit(observations)
        self._hmm = hmm
        self._regularize_covariances()
        self._label_states()
        logger.info("HMM fitted with %d states. State map: %s", self.n_states, self._state_map)

    def _label_states(self) -> None:
        """Label hidden states by ordering on mean realized_vol (col 0)."""
        if self._hmm is None:
            return
        mean_vols = self._hmm.means_[:, 0]  # realized_vol means per state
        mean_mom = self._hmm.means_[:, 1] if self._hmm.means_.shape[1] > 1 else np.zeros_like(mean_vols)
        order = np.lexsort((mean_mom, mean_vols))  # stable tie-break: vol then momentum
        labels = [TREND, CHOP, RISK_OFF]     # low → high vol
        self._state_map = {int(order[i]): labels[i] for i in range(self.n_states)}
        self._state_order = [int(x) for x in order]

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict_state(self, observations: np.ndarray) -> tuple[str, dict[str, float]]:
        """Predict the current regime and return state probabilities.

        Parameters
        ----------
        observations:
            Array of shape (T, 2) — all observations up to the current bar.

        Returns
        -------
        (state_label, {label: probability})
        """
        if self._hmm is None:
            raise RuntimeError("HMM model is not fitted. Call fit() or load() first.")
        try:
            return self._decode_state(observations)
        except ValueError as exc:
            logger.warning("HMM decode failed, retrying with covariance regularization: %s", exc)
            self._regularize_covariances()
            try:
                return self._decode_state(observations)
            except ValueError as retry_exc:
                logger.warning("HMM decode still failed, using distance fallback: %s", retry_exc)
                return self._fallback_state(observations)

    def _decode_state(self, observations: np.ndarray) -> tuple[str, dict[str, float]]:
        _, state_seq = self._hmm.decode(observations, algorithm="viterbi")
        current_state_idx = int(state_seq[-1])
        posterior = self._hmm.predict_proba(observations)[-1]
        proba_by_label = {
            self._state_map.get(i, f"STATE_{i}"): float(posterior[i]) for i in range(self.n_states)
        }
        label = self._state_map.get(current_state_idx, f"STATE_{current_state_idx}")
        return label, proba_by_label

    def _fallback_state(self, observations: np.ndarray) -> tuple[str, dict[str, float]]:
        if self._hmm is None or getattr(self._hmm, "means_", None) is None:
            raise RuntimeError("HMM fallback requires fitted state means")

        latest = np.asarray(observations)[-1]
        means = np.asarray(self._hmm.means_, dtype=float)
        distances = np.linalg.norm(means - latest, axis=1)
        scaled = -distances
        scaled -= np.max(scaled)
        weights = np.exp(scaled)
        total = float(np.sum(weights))
        if not np.isfinite(total) or total <= 0:
            weights = np.ones(self.n_states, dtype=float) / float(self.n_states)
        else:
            weights = weights / total
        current_state_idx = int(np.argmax(weights))
        label = self._state_map.get(current_state_idx, f"STATE_{current_state_idx}")
        proba_by_label = {
            self._state_map.get(i, f"STATE_{i}"): float(weights[i]) for i in range(self.n_states)
        }
        return label, proba_by_label

    def _regularize_covariances(self, epsilon: float = 1e-6) -> None:
        if self._hmm is None or not hasattr(self._hmm, "covars_"):
            return
        covars = np.asarray(self._hmm.covars_, dtype=float)
        if covars.ndim != 3:
            return
        regularized = []
        for covar in covars:
            symmetric = 0.5 * (covar + covar.T)
            scale = max(float(np.trace(np.abs(symmetric))) / max(symmetric.shape[0], 1), 1.0)
            ridge = max(epsilon, scale * 1e-8)
            eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
            clipped = np.clip(eigenvalues, ridge, None)
            repaired = eigenvectors @ np.diag(clipped) @ eigenvectors.T
            regularized.append(0.5 * (repaired + repaired.T))
        self._hmm.covars_ = np.asarray(regularized, dtype=float)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """Serialize the fitted HMM model to disk."""
        import joblib  # noqa: PLC0415
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"hmm": self._hmm, "state_map": self._state_map}, out)
        logger.info("HMM model saved to %s", out)

    def load(self, path: str | Path) -> None:
        """Load a previously serialized HMM model."""
        import joblib  # noqa: PLC0415
        data = joblib.load(Path(path))
        self._hmm = data["hmm"]
        self._state_map = data["state_map"]
        self._regularize_covariances()
        logger.info("HMM model loaded from %s", path)

    @property
    def is_fitted(self) -> bool:
        return self._hmm is not None

    @property
    def state_map(self) -> dict[int, str]:
        return dict(self._state_map)

    @property
    def state_metadata(self) -> dict[str, object]:
        means = []
        if self._hmm is not None:
            for idx, row in enumerate(self._hmm.means_):
                means.append({"state_idx": int(idx), "mean_vol": float(row[0]), "mean_mom": float(row[1]) if len(row) > 1 else 0.0})
        return {
            "state_map": dict(self._state_map),
            "state_order": list(self._state_order),
            "means": means,
        }
