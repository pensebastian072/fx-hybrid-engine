"""Heuristic regime orchestrator."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from fx_lean_engine.types import RegimeState


def _sigmoid(value: float) -> float:
    value = max(min(float(value), 50.0), -50.0)
    return 1.0 / (1.0 + np.exp(-value))


@dataclass(slots=True)
class RegimeOrchestrator:
    """Heuristic classifier producing TREND/CHOP/RISK_OFF."""

    symbols: list[str]
    vol_window: int = 30
    trend_window: int = 30
    chop_window: int = 20
    risk_off_vol_threshold: float = 0.008
    trend_strength_threshold: float = 0.6
    chop_threshold: float = 0.55

    _history: dict[str, deque[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.symbols = [str(symbol).upper().strip() for symbol in self.symbols]
        window = max(self.vol_window, self.trend_window, self.chop_window) + 5
        self._history = {symbol: deque(maxlen=window) for symbol in self.symbols}

    def update(
        self,
        close_snapshot: dict[str, float],
        feature_snapshot: dict[str, object] | None = None,
        timestamp: datetime | None = None,
    ) -> RegimeState:
        """Update state with latest closes and classify regime."""
        _ = feature_snapshot
        _ = timestamp
        for symbol, close in close_snapshot.items():
            key = str(symbol).upper().strip()
            if key in self._history:
                self._history[key].append(float(close))

        vols: list[float] = []
        trend_strengths: list[float] = []
        chops: list[float] = []

        for symbol in self.symbols:
            data = np.asarray(list(self._history[symbol]), dtype=float)
            if data.size < max(self.vol_window, self.trend_window, self.chop_window):
                continue

            returns = np.diff(data) / np.maximum(data[:-1], 1e-12)
            vol = float(np.std(returns[-self.vol_window :], ddof=1)) if returns.size >= self.vol_window else 0.0
            vols.append(vol)

            trend_slice = data[-self.trend_window :]
            x = np.arange(trend_slice.size, dtype=float)
            x_centered = x - np.mean(x)
            slope = float(np.sum(x_centered * (trend_slice - np.mean(trend_slice)))) / max(float(np.sum(x_centered**2)), 1e-12)
            slope_pct = 0.0 if trend_slice[-1] == 0 else slope / trend_slice[-1]
            trend_strength = abs(slope_pct) / max(vol, 1e-8)
            trend_strengths.append(float(trend_strength))

            chop_slice = data[-self.chop_window :]
            abs_sum = float(np.sum(np.abs(np.diff(chop_slice))))
            net = float(abs(chop_slice[-1] - chop_slice[0]))
            chop = 1.0 - (net / max(abs_sum, 1e-12))
            chops.append(float(min(max(chop, 0.0), 1.0)))

        if not vols:
            return RegimeState(
                state="CHOP",
                p_trend=0.33,
                p_chop=0.34,
                p_risk_off=0.33,
                trend_weight=0.2,
                pairs_weight=0.8,
            )

        vol_m = float(np.median(vols))
        trend_m = float(np.median(trend_strengths)) if trend_strengths else 0.0
        chop_m = float(np.median(chops)) if chops else 0.5

        risk_score = _sigmoid((vol_m - self.risk_off_vol_threshold) / max(self.risk_off_vol_threshold, 1e-8) * 6.0)
        trend_score = _sigmoid((trend_m - self.trend_strength_threshold) * 3.0) * (1.0 - min(max(chop_m, 0.0), 1.0))
        chop_score = min(max(chop_m * (1.0 - min(trend_m / max(self.trend_strength_threshold * 2.0, 1e-8), 1.0)), 0.0), 1.0)

        total = max(risk_score + trend_score + chop_score, 1e-12)
        p_risk_off = risk_score / total
        p_trend = trend_score / total
        p_chop = chop_score / total

        if p_risk_off >= max(p_trend, p_chop):
            state = "RISK_OFF"
            trend_weight = 0.0
            pairs_weight = 0.0
        elif p_trend >= p_chop:
            state = "TREND"
            trend_weight = 0.8
            pairs_weight = 0.2
        else:
            state = "CHOP"
            trend_weight = 0.2
            pairs_weight = 0.8

        return RegimeState(
            state=state,
            p_trend=float(p_trend),
            p_chop=float(p_chop),
            p_risk_off=float(p_risk_off),
            trend_weight=float(trend_weight),
            pairs_weight=float(pairs_weight),
        )
