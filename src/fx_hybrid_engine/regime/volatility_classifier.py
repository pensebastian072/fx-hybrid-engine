"""Volatility-based regime classifier.

Classifies market bars into LOW_VOL / MED_VOL / HIGH_VOL regimes using
rolling realized volatility percentile buckets.  Designed to complement
(not replace) the HMM-based RegimeOrchestrator.

Inspired by GARCH-style volatility regime segmentation from:
- stefan-jansen/machine-learning-for-trading ch9
  (09_time_series_models/03_arch_garch_models.ipynb)

The classifier is stateless (call ``classify_series`` for a full history,
or ``classify_bar`` with a running window).  No ML model training is required;
thresholds are derived from empirical percentiles.
"""
from __future__ import annotations

import logging
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger("fxhe.regime.volatility_classifier")

# Regime labels for volatility-based classification
VOL_REGIME_LOW = "LOW_VOL"
VOL_REGIME_MED = "MED_VOL"
VOL_REGIME_HIGH = "HIGH_VOL"


class VolRegime(str, Enum):
    LOW = VOL_REGIME_LOW
    MED = VOL_REGIME_MED
    HIGH = VOL_REGIME_HIGH


class VolatilityRegimeClassifier:
    """Classifies rolling realized-vol into LOW / MED / HIGH regimes.

    Thresholds are computed from empirical percentiles of the training window,
    making them adaptive to each symbol's typical vol level.

    Parameters
    ----------
    vol_window : int
        Lookback in bars for rolling realized volatility (std of log returns).
    percentile_low : float
        Percentile boundary between LOW and MED regimes (default 33rd).
    percentile_high : float
        Percentile boundary between MED and HIGH regimes (default 67th).
    smooth_window : int
        Optional secondary smoothing window for the vol estimate.  Set to 1
        to disable smoothing.
    annualize : bool
        If True, annualize the vol estimate (multiply by sqrt(252)).

    Usage
    -----
    >>> clf = VolatilityRegimeClassifier()
    >>> clf.fit(close_series)           # computes adaptive thresholds
    >>> regimes = clf.classify_series(close_series)   # pd.Series of VolRegime
    >>> regime_now = clf.classify_bar(close_series)   # single VolRegime value
    """

    def __init__(
        self,
        vol_window: int = 20,
        percentile_low: float = 33.0,
        percentile_high: float = 67.0,
        smooth_window: int = 3,
        annualize: bool = True,
    ) -> None:
        self.vol_window = vol_window
        self.percentile_low = percentile_low
        self.percentile_high = percentile_high
        self.smooth_window = smooth_window
        self.annualize = annualize
        self._thresh_low: float | None = None
        self._thresh_high: float | None = None

    @property
    def is_fitted(self) -> bool:
        return self._thresh_low is not None and self._thresh_high is not None

    # ------------------------------------------------------------------
    # Fitting (threshold calibration)
    # ------------------------------------------------------------------

    def fit(self, close: pd.Series) -> None:
        """Compute vol percentile thresholds from a training price series."""
        vol = self._rolling_vol(close)
        valid = vol.dropna()
        if len(valid) < 10:
            logger.warning("Too few observations to fit VolatilityRegimeClassifier")
            return
        self._thresh_low = float(np.percentile(valid, self.percentile_low))
        self._thresh_high = float(np.percentile(valid, self.percentile_high))
        logger.info(
            "VolatilityRegimeClassifier fitted: LOW<%.6f, HIGH>%.6f",
            self._thresh_low,
            self._thresh_high,
        )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _rolling_vol(self, close: pd.Series) -> pd.Series:
        log_ret = np.log(close / close.shift(1))
        vol = log_ret.rolling(window=self.vol_window, min_periods=self.vol_window).std()
        if self.annualize:
            vol = vol * np.sqrt(252)
        if self.smooth_window > 1:
            vol = vol.rolling(window=self.smooth_window, min_periods=1).mean()
        return vol

    def _classify_vol(self, vol_value: float) -> VolRegime:
        if self._thresh_low is None or self._thresh_high is None:
            return VolRegime.MED
        if vol_value <= self._thresh_low:
            return VolRegime.LOW
        if vol_value >= self._thresh_high:
            return VolRegime.HIGH
        return VolRegime.MED

    def classify_series(self, close: pd.Series) -> pd.Series:
        """Classify every bar in ``close`` and return a Series of VolRegime.

        If ``fit`` has not been called, thresholds are computed from this same
        series (in-sample; no look-ahead on the thresholds themselves, but be
        aware that this is not a rolling out-of-sample classification).
        """
        if not self.is_fitted:
            self.fit(close)
        vol = self._rolling_vol(close)
        regimes = vol.map(lambda v: self._classify_vol(v) if not pd.isna(v) else VolRegime.MED)
        regimes.name = "vol_regime"
        return regimes

    def classify_bar(self, close: pd.Series) -> VolRegime:
        """Return the regime for the most recent bar in ``close``.

        Requires that ``fit`` has been called on a training window first.
        """
        vol = self._rolling_vol(close)
        last = vol.iloc[-1]
        if pd.isna(last):
            return VolRegime.MED
        return self._classify_vol(float(last))

    def current_vol(self, close: pd.Series) -> float | None:
        """Return the most recent rolling vol value (or None if warmup incomplete)."""
        vol = self._rolling_vol(close)
        last = vol.iloc[-1]
        return float(last) if not pd.isna(last) else None

    def summary(self) -> dict[str, object]:
        """Return threshold configuration as a dict for logging/artifacts."""
        return {
            "vol_window": self.vol_window,
            "percentile_low": self.percentile_low,
            "percentile_high": self.percentile_high,
            "smooth_window": self.smooth_window,
            "annualize": self.annualize,
            "thresh_low": self._thresh_low,
            "thresh_high": self._thresh_high,
            "fitted": self.is_fitted,
        }
