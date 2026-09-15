"""Shared dataclasses for engine signal outputs."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class EngineType(str, Enum):
    PAIRS = "pairs"
    TREND = "trend"
    ML_ENSEMBLE = "ml_ensemble"


@dataclass(slots=True)
class Signal:
    """A single directional signal for one instrument."""
    symbol: str
    direction: Direction
    size: float                   # target notional weight (0.0 – 1.0)
    engine: EngineType
    timestamp: pd.Timestamp
    confidence: float = 1.0       # model probability or rule strength
    metadata: dict = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.direction != Direction.FLAT and self.size > 0


@dataclass(slots=True)
class EngineOutput:
    """Collection of signals from one engine for one bar."""
    engine: EngineType
    timestamp: pd.Timestamp
    signals: list[Signal] = field(default_factory=list)

    def active_signals(self) -> list[Signal]:
        return [s for s in self.signals if s.is_active()]
