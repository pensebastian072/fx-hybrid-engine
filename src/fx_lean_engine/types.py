"""Shared data contracts for FX LEAN engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass(slots=True)
class Bar:
    """Canonical OHLCV bar."""

    symbol: str
    start: datetime
    end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(slots=True)
class FeatureVector:
    """Normalized FX feature vector."""

    symbol: str
    timestamp: datetime
    close: float
    ret_1: float
    log_ret_1: float
    vol_20_pct: float
    zret_20: float
    range_pct: float


@dataclass(slots=True)
class PairsSignal:
    """Pairs signal payload."""

    pair: tuple[str, str]
    zscore: float
    hedge_ratio: float
    direction: str
    confidence: float
    pair_status: str = "TRADABLE"


@dataclass(slots=True)
class TrendSignal:
    """Trend signal payload."""

    symbol: str
    p_up: float
    p_down: float
    confidence: float
    direction: str


@dataclass(slots=True)
class RegimeState:
    """Regime output with probabilities and weights."""

    state: str
    p_trend: float
    p_chop: float
    p_risk_off: float
    trend_weight: float
    pairs_weight: float


@dataclass(slots=True)
class TradeIntent:
    """Engine-generated trade intent."""

    engine: str
    action: str
    symbol: str | None
    pair: tuple[str, str] | None
    direction: str
    notional_pct_nav: float
    confidence: float
    reason: str
    pair_status: str | None = None


@dataclass(slots=True)
class RiskDecision:
    """Risk gate decision for one intent."""

    approved: bool
    reason: str


@dataclass(slots=True)
class PortfolioRiskState:
    """Minimal state required for runtime risk caps."""

    gross_leverage: float = 0.0
    symbol_notional_pct_nav: dict[str, float] | None = None
    pair_notional_pct_nav: dict[str, float] | None = None
    open_pairs: int = 0
    open_trend_positions: int = 0

    def __post_init__(self) -> None:
        if self.symbol_notional_pct_nav is None:
            self.symbol_notional_pct_nav = {}
        if self.pair_notional_pct_nav is None:
            self.pair_notional_pct_nav = {}


@dataclass(slots=True)
class PipelineArtifacts:
    """In-memory artifacts that map to persisted outputs."""

    signals: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]]
    regime: list[dict[str, Any]]
    features: list[dict[str, Any]]
    targets: list[dict[str, Any]]
    bar_health: list[dict[str, Any]]
    risk_events: list[dict[str, Any]]
    pairs_candidates: list[dict[str, Any]]
    pairs_scan: list[dict[str, Any]]
    pair_state_events: list[dict[str, Any]]
    pnl_by_pair: list[dict[str, Any]]
    bars: list[dict[str, Any]]
    fills: list[dict[str, Any]]
    broker_events: list[dict[str, Any]]
    regime_posteriors: list[dict[str, Any]]
    regime_events: list[dict[str, Any]]
    regime_hmm_params: dict[str, Any] | None
    regime_state_map: dict[str, Any] | None
    # Per-trade training rows: (entry_features, realized_outcome) for supervised learning.
    trade_training_rows: list[dict[str, Any]]
    # Per-trade analytics computed from realized fills + bar price path.
    trade_analytics: list[dict[str, Any]]


@dataclass(slots=True)
class BarHealthEvent:
    """Bar integrity event contract."""

    symbol: str
    timestamp: datetime
    event_type: str
    detail: str
    severity: str


class PairStatus(StrEnum):
    """Tradability state for pairs."""

    TRADABLE = "TRADABLE"
    WATCH = "WATCH"
    DISABLED = "DISABLED"


@dataclass(slots=True)
class PairFitResult:
    """Cointegration fit output for one pair at scan time."""

    pair: tuple[str, str]
    beta: float
    intercept: float
    p_value: float
    spread_std: float
    half_life: float
    beta_drift: float
    spread_last_z: float
    timestamp: datetime


@dataclass(slots=True)
class PairValidityState:
    """Persisted tradability state for one pair."""

    pair: tuple[str, str]
    status: PairStatus = PairStatus.WATCH
    last_pass_time: datetime | None = None
    last_fail_time: datetime | None = None
    disabled_until: datetime | None = None
    pval_history: list[float] | None = None
    pass_scans: int = 0
    fail_scans: int = 0
    break_scans: int = 0
    scans_total: int = 0
    beta_prev: float | None = None
    spread_std_history: list[float] | None = None
    status_reason: str = "INIT"

    def __post_init__(self) -> None:
        if self.pval_history is None:
            self.pval_history = []
        if self.spread_std_history is None:
            self.spread_std_history = []


@runtime_checkable
class PairsEngineLike(Protocol):
    """Minimal pairs-engine interface used by runtime."""

    pairs: list[tuple[str, str]]

    def update(
        self,
        close_snapshot: dict[str, float],
        timestamp: datetime,
        pair_status_map: dict[tuple[str, str], str] | None = None,
    ) -> tuple[list[PairsSignal], list[TradeIntent]]:
        """Emit pairs signals and intents."""


@runtime_checkable
class TrendEngineLike(Protocol):
    """Minimal trend-engine interface used by runtime."""

    def update(self, close_snapshot: dict[str, float]) -> tuple[list[TrendSignal], list[TradeIntent]]:
        """Emit trend signals and intents."""


@runtime_checkable
class RegimeEngineLike(Protocol):
    """Minimal regime-engine interface used by runtime."""

    def update(
        self,
        close_snapshot: dict[str, float],
        feature_snapshot: dict[str, FeatureVector] | None = None,
        timestamp: datetime | None = None,
    ) -> RegimeState:
        """Emit one regime state."""


PairsEngineFactory = Callable[[list[tuple[str, str]], int, Any, Any, list[str]], PairsEngineLike]
TrendEngineFactory = Callable[[list[str], Any], TrendEngineLike]
RegimeEngineFactory = Callable[[list[str], Any], RegimeEngineLike]
