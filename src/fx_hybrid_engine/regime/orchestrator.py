"""Regime orchestrator: gates engine signals based on current HMM state."""
from __future__ import annotations
import logging
import numpy as np
import pandas as pd
from typing import Literal

from fx_hybrid_engine.engines.types import Direction, EngineOutput, EngineType, Signal
from fx_hybrid_engine.features.indicators import rolling_vol, momentum_slope
from fx_hybrid_engine.regime.hmm import RegimeHMM, TREND, CHOP, RISK_OFF
from fx_hybrid_engine.utils.config import RegimeConfig, RiskConfig

logger = logging.getLogger("fxhe.regime.orchestrator")


class RegimeOrchestrator:
    """Loads and runs the HMM, then gates pairs/trend signals accordingly.

    Regime rules:
    - TREND:    allow only trend-engine signals; zero pairs signals
    - CHOP:     allow only pairs-engine signals; zero trend signals
    - RISK_OFF: zero both; reduce position sizes to risk_off_size_multiplier
    """

    def __init__(self, regime_config: RegimeConfig, risk_config: RiskConfig) -> None:
        self.regime_config = regime_config
        self.risk_config = risk_config
        self._hmm = RegimeHMM(n_states=regime_config.n_states)
        self._current_state: str = CHOP   # default until model loaded
        self._state_probabilities: dict[str, float] = self._default_probabilities(CHOP)

    def _default_probabilities(self, label: str) -> dict[str, float]:
        return {
            TREND: 1.0 if label == TREND else 0.0,
            CHOP: 1.0 if label == CHOP else 0.0,
            RISK_OFF: 1.0 if label == RISK_OFF else 0.0,
        }

    def load_model(self) -> bool:
        """Load the serialized HMM model. Returns True on success."""
        try:
            self._hmm.load(self.regime_config.model_path)
            return True
        except Exception:
            logger.exception("Failed to load HMM model from %s", self.regime_config.model_path)
            return False

    def update_regime(self, data: dict[str, pd.DataFrame]) -> str:
        """Compute observations from multi-symbol data and update current regime.

        Observations per bar are averaged across symbols:
          [mean_realized_vol, mean_momentum_score]

        Returns the current regime label.
        """
        if not self._hmm.is_fitted:
            logger.warning("HMM not fitted — defaulting to CHOP regime")
            self._current_state = CHOP
            self._state_probabilities = self._default_probabilities(CHOP)
            return CHOP

        obs_list = []
        for df in data.values():
            if "close" not in df.columns or len(df) < self.regime_config.vol_window + 2:
                continue
            close = df["close"]
            vol = rolling_vol(close, window=self.regime_config.vol_window, annualize=True)
            mom = momentum_slope(close, window=self.regime_config.vol_window)
            combined = pd.DataFrame({"vol": vol, "mom": mom}).dropna()
            obs_list.append(combined.values)

        if not obs_list:
            if not self._state_probabilities:
                self._state_probabilities = self._default_probabilities(self._current_state)
            return self._current_state

        # Average across symbols, use last obs_window bars
        min_len = min(len(o) for o in obs_list)
        obs_array = np.mean(
            [o[-min_len:] for o in obs_list], axis=0
        )[-self.regime_config.obs_window:]

        if len(obs_array) < 2:
            if not self._state_probabilities:
                self._state_probabilities = self._default_probabilities(self._current_state)
            return self._current_state

        return self.update_regime_from_observations(obs_array)

    def update_regime_from_observations(self, observations: np.ndarray) -> str:
        """Update regime directly from precomputed observation array."""
        if not self._hmm.is_fitted:
            self._current_state = CHOP
            self._state_probabilities = {TREND: 0.0, CHOP: 1.0, RISK_OFF: 0.0}
            return self._current_state
        if len(observations) < 2:
            return self._current_state
        try:
            label, proba = self._hmm.predict_state(observations)
            self._current_state = label
            self._state_probabilities = proba
            logger.debug("Regime: %s | proba: %s", label, proba)
        except Exception:
            logger.exception("HMM inference failed — keeping previous regime %s", self._current_state)
            self._state_probabilities = self._default_probabilities(self._current_state)
        return self._current_state

    def gate(
        self,
        pairs_output: EngineOutput,
        trend_output: EngineOutput,
        timestamp: pd.Timestamp,
        mode: Literal["hybrid", "pairs_only", "trend_only"] = "hybrid",
    ) -> list[Signal]:
        """Apply regime gating to engine outputs.

        Returns the merged list of allowed signals.
        """
        state = self._current_state
        multiplier = 1.0

        if state == RISK_OFF:
            multiplier = self.risk_config.risk_off_size_multiplier
            allowed_pairs: list[Signal] = []
            allowed_trend: list[Signal] = []
        elif mode == "pairs_only":
            allowed_pairs = list(pairs_output.signals)
            allowed_trend = []
        elif mode == "trend_only":
            allowed_pairs = []
            allowed_trend = list(trend_output.signals)
        elif state == TREND:
            allowed_pairs = []
            allowed_trend = list(trend_output.signals)
        elif state == CHOP:
            allowed_pairs = list(pairs_output.signals)
            allowed_trend = []
        else:
            # Unknown state — conservative: allow neither
            allowed_pairs = []
            allowed_trend = []

        gated: list[Signal] = []
        for sig in allowed_pairs + allowed_trend:
            if sig.direction == Direction.FLAT or sig.size == 0:
                gated.append(sig)
            else:
                import dataclasses  # noqa: PLC0415
                gated.append(dataclasses.replace(sig, size=sig.size * multiplier))

        return gated

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def state_probabilities(self) -> dict[str, float]:
        return self._state_probabilities.copy()

    def snapshot(self, timestamp: pd.Timestamp) -> dict[str, object]:
        """Structured regime snapshot for logging and artifact emission."""
        probs = self.state_probabilities
        return {
            "timestamp": pd.Timestamp(timestamp).isoformat(),
            "regime_label": self.current_state,
            "TREND": float(probs.get(TREND, 0.0)),
            "CHOP": float(probs.get(CHOP, 0.0)),
            "RISK_OFF": float(probs.get(RISK_OFF, 0.0)),
        }
