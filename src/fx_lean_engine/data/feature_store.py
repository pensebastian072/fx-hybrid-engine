"""Feature store for per-symbol rolling feature vectors."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict
from typing import Any

import numpy as np

from fx_lean_engine.types import Bar, FeatureVector

_WARMUP_WINDOW = 20


class _SymbolFeatureState:
    """Rolling feature state for a single symbol."""

    def __init__(self, warmup_bars: int) -> None:
        self._warmup = max(int(warmup_bars), 2)
        self._closes: deque[float] = deque(maxlen=max(self._warmup, _WARMUP_WINDOW) + 5)
        self._bars_seen = 0
        self._last_vector: FeatureVector | None = None

    def update(self, bar: Bar) -> FeatureVector | None:
        close = float(bar.close)
        self._closes.append(close)
        self._bars_seen += 1

        if self._bars_seen < self._warmup:
            return None

        closes = np.asarray(self._closes, dtype=float)
        ret_1 = (closes[-1] / closes[-2] - 1.0) if len(closes) >= 2 else 0.0
        log_ret_1 = math.log(closes[-1] / closes[-2]) if len(closes) >= 2 and closes[-2] > 0 else 0.0

        window = closes[-_WARMUP_WINDOW:] if len(closes) >= _WARMUP_WINDOW else closes
        if len(window) >= 2:
            rets = np.diff(window) / window[:-1]
            vol_20_pct = float(np.std(rets, ddof=1)) * 100.0
            mean_ret = float(np.mean(rets))
            std_ret = float(np.std(rets, ddof=1))
            zret_20 = (ret_1 - mean_ret) / std_ret if std_ret > 1e-12 else 0.0
        else:
            vol_20_pct = 0.0
            zret_20 = 0.0

        range_pct = (float(bar.high) - float(bar.low)) / float(bar.close) * 100.0 if float(bar.close) > 0 else 0.0

        vec = FeatureVector(
            symbol=str(bar.symbol).upper().strip(),
            timestamp=bar.end,
            close=close,
            ret_1=float(ret_1),
            log_ret_1=float(log_ret_1),
            vol_20_pct=float(vol_20_pct),
            zret_20=float(zret_20),
            range_pct=float(range_pct),
        )
        self._last_vector = vec
        return vec

    @property
    def last_vector(self) -> FeatureVector | None:
        return self._last_vector

    @property
    def last_close(self) -> float | None:
        return float(self._closes[-1]) if self._closes else None


class FeatureStore:
    """Multi-symbol feature store."""

    def __init__(self, warmup_bars: int = 20) -> None:
        self._warmup = int(warmup_bars)
        self._states: dict[str, _SymbolFeatureState] = {}
        self._all_vectors: list[FeatureVector] = []
        self._bars_total = 0
        self._vectors_emitted = 0

    def _get_state(self, symbol: str) -> _SymbolFeatureState:
        key = str(symbol).upper().strip()
        if key not in self._states:
            self._states[key] = _SymbolFeatureState(self._warmup)
        return self._states[key]

    def update(self, bar: Bar) -> FeatureVector | None:
        """Process one bar; return a FeatureVector or None during warmup."""
        self._bars_total += 1
        state = self._get_state(bar.symbol)
        vec = state.update(bar)
        if vec is not None:
            self._all_vectors.append(vec)
            self._vectors_emitted += 1
        return vec

    def latest_close_snapshot(self) -> dict[str, float]:
        """Return the latest close price per symbol."""
        out: dict[str, float] = {}
        for key, state in self._states.items():
            close = state.last_close
            if close is not None:
                out[key] = close
        return out

    def latest_feature_snapshot(self) -> dict[str, FeatureVector]:
        """Return the latest FeatureVector per symbol."""
        out: dict[str, FeatureVector] = {}
        for key, state in self._states.items():
            vec = state.last_vector
            if vec is not None:
                out[key] = vec
        return out

    def latest_feature_rows(self) -> list[dict[str, Any]]:
        """Return all emitted feature rows as dicts."""
        rows = []
        for vec in self._all_vectors:
            row = asdict(vec)
            row["timestamp"] = vec.timestamp.isoformat()
            rows.append(row)
        return rows

    def counters(self) -> dict[str, int]:
        """Return internal counters."""
        return {
            "bars_total": self._bars_total,
            "feature_updates_emitted": self._vectors_emitted,
            "feature_updates_nan_rejected": 0,
            "symbols_tracked": len(self._states),
        }
