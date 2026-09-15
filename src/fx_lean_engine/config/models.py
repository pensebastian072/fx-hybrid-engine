"""Typed config schemas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(slots=True)
class UniverseConfig:
    """Universe contract."""

    asset_type: str = "forex"
    pairs: list[str] | None = None
    subscription_resolution: str = "Minute"
    consolidated_bar_minutes: int = 15

    def __post_init__(self) -> None:
        if self.asset_type.strip().lower() != "forex":
            raise ValueError("universe.asset_type must be 'forex'")
        if not self.pairs:
            raise ValueError("universe.pairs must be non-empty")
        clean: list[str] = []
        for pair in self.pairs:
            text = str(pair).upper().replace("/", "").strip()
            if len(text) != 6 or not text.isalpha():
                raise ValueError(f"invalid FX pair in universe config: {pair}")
            clean.append(text)
        self.pairs = clean
        if self.subscription_resolution.strip() != "Minute":
            raise ValueError("universe.subscription_resolution must be 'Minute' for this phase")
        self.consolidated_bar_minutes = int(self.consolidated_bar_minutes)
        if self.consolidated_bar_minutes <= 0:
            raise ValueError("universe.consolidated_bar_minutes must be > 0")


@dataclass(slots=True)
class PairsConfig:
    """Pairs engine contract."""

    pairs: list[list[str]] | None = None
    lookback_bars: int = 500
    entry_z: float = 2.0
    exit_z: float = 0.5
    max_holding_bars: int = 200

    def __post_init__(self) -> None:
        if not self.pairs:
            raise ValueError("pairs.pairs must be non-empty")
        clean_pairs: list[list[str]] = []
        for pair in self.pairs:
            if len(pair) != 2:
                raise ValueError(f"pairs entries must have two symbols: {pair}")
            left = str(pair[0]).upper().replace("/", "").strip()
            right = str(pair[1]).upper().replace("/", "").strip()
            if len(left) != 6 or len(right) != 6:
                raise ValueError(f"invalid pair format: {pair}")
            if left[3:] != right[3:]:
                raise ValueError(f"pairs must share quote currency in this phase: {pair}")
            clean_pairs.append([left, right])
        self.pairs = clean_pairs
        self.lookback_bars = max(int(self.lookback_bars), 20)
        self.entry_z = max(float(self.entry_z), 0.1)
        self.exit_z = max(float(self.exit_z), 0.0)
        self.max_holding_bars = max(int(self.max_holding_bars), 1)


@dataclass(slots=True)
class RuntimeConfig:
    """Runtime, risk, and brokerage controls."""

    execution_mode: str = "backtest"
    brokerage: str = "oanda"
    account_type: str = "margin"
    data_source: str = "cloud"
    local_data_dir: str | None = None
    phase2_pairs_gating_enabled: bool = False
    live_output_root: str = "outputs/live"
    live_persistence_enabled: bool | None = None
    data_stale_minutes: int = 45

    max_gross_leverage: float = 2.0
    max_pair_notional_pct_nav: float = 0.25
    max_symbol_notional_pct_nav: float = 0.15
    max_open_pairs: int = 2
    max_open_trend_positions: int = 3

    trend_notional_pct_nav: float = 0.10
    pairs_notional_pct_nav: float = 0.12
    block_new_entries: bool = False
    kill_switch_enabled: bool = False
    kill_switch_reason: str = "MANUAL_KILL_SWITCH"
    gap_warn_threshold_minutes: int = 30
    strict_bar_ordering: bool = True

    # Cross-engine signal alignment gate (Task 3).
    # When True, trend opens are blocked unless the same symbol appears in a
    # pairs open intent on the same bar.
    require_signal_alignment: bool = False
    alignment_min_confidence: float = 0.10

    oanda_environment: str = "practice"
    oanda_account_id_env: str = "OANDA_ACCOUNT_ID"
    oanda_api_token_env: str = "OANDA_API_TOKEN"

    def __post_init__(self) -> None:
        self.execution_mode = str(self.execution_mode).strip().lower()
        if self.execution_mode not in {"backtest", "paper", "live"}:
            raise ValueError("runtime.execution_mode must be backtest|paper|live")
        if str(self.brokerage).strip().lower() != "oanda":
            raise ValueError("runtime.brokerage must be oanda")
        self.account_type = str(self.account_type).strip().lower()
        if self.account_type not in {"margin", "cash"}:
            raise ValueError("runtime.account_type must be margin|cash")
        self.data_source = str(self.data_source).strip().lower()
        if self.data_source not in {"cloud", "local"}:
            raise ValueError("runtime.data_source must be cloud|local")
        if self.data_source == "local" and not str(self.local_data_dir or "").strip():
            raise ValueError("runtime.local_data_dir is required when data_source=local")

        self.live_output_root = str(self.live_output_root).strip() or "outputs/live"
        if self.live_persistence_enabled is None:
            self.live_persistence_enabled = self.execution_mode in {"paper", "live"}
        else:
            self.live_persistence_enabled = bool(self.live_persistence_enabled)
        self.data_stale_minutes = max(int(self.data_stale_minutes), 1)

        self.max_gross_leverage = max(float(self.max_gross_leverage), 0.0)
        self.max_pair_notional_pct_nav = min(max(float(self.max_pair_notional_pct_nav), 0.0), 1.0)
        self.max_symbol_notional_pct_nav = min(max(float(self.max_symbol_notional_pct_nav), 0.0), 1.0)
        self.max_open_pairs = max(int(self.max_open_pairs), 0)
        self.max_open_trend_positions = max(int(self.max_open_trend_positions), 0)

        self.trend_notional_pct_nav = min(max(float(self.trend_notional_pct_nav), 0.0), 1.0)
        self.pairs_notional_pct_nav = min(max(float(self.pairs_notional_pct_nav), 0.0), 1.0)
        self.kill_switch_reason = str(self.kill_switch_reason).strip() or "MANUAL_KILL_SWITCH"
        self.gap_warn_threshold_minutes = max(int(self.gap_warn_threshold_minutes), 1)

        self.alignment_min_confidence = min(max(float(self.alignment_min_confidence), 0.0), 1.0)

        self.oanda_environment = str(self.oanda_environment).strip().lower()
        if self.oanda_environment not in {"practice", "trade"}:
            raise ValueError("runtime.oanda_environment must be practice|trade")


@dataclass(slots=True)
class BacktestConfig:
    """Backtest run settings."""

    name: str
    start_date: str
    end_date: str
    initial_cash: float = 100000.0
    symbols: list[str] | None = None

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
        if not self.name:
            raise ValueError("backtest.name is required")

        start = date.fromisoformat(str(self.start_date))
        end = date.fromisoformat(str(self.end_date))
        if end <= start:
            raise ValueError("backtest.end_date must be after start_date")
        self.start_date = start.isoformat()
        self.end_date = end.isoformat()

        self.initial_cash = max(float(self.initial_cash), 1000.0)
        clean_symbols: list[str] = []
        for symbol in self.symbols or []:
            text = str(symbol).upper().replace("/", "").strip()
            if len(text) == 6 and text.isalpha():
                clean_symbols.append(text)
        self.symbols = clean_symbols


@dataclass(slots=True)
class PairsPolicyConfig:
    """Phase 2 pairs policy contract."""

    pairs: list[list[str]] | None = None
    groups: dict[str, list[str]] | None = None
    avoid_pairs: list[list[str]] | None = None
    lookback_bars: int = 500
    scan_frequency: str = "daily"
    p_enter: float = 0.05
    p_exit: float = 0.15
    p_break: float = 0.25
    p_recover: float = 0.05
    break_scans_required: int = 3
    recover_scans_required: int = 2
    beta_jump_threshold: float = 0.25
    variance_break_mult: float = 2.5
    disable_cooldown_bars: int = 288
    time_stop_half_life_mult: float = 3.0
    entry_z: float = 2.0
    exit_z: float = 0.5

    def __post_init__(self) -> None:
        self.scan_frequency = str(self.scan_frequency).strip().lower()
        if self.scan_frequency not in {"daily"}:
            raise ValueError("pairs_policy.scan_frequency must be 'daily'")

        self.lookback_bars = max(int(self.lookback_bars), 50)
        self.p_enter = min(max(float(self.p_enter), 0.0), 1.0)
        self.p_exit = min(max(float(self.p_exit), 0.0), 1.0)
        self.p_break = min(max(float(self.p_break), 0.0), 1.0)
        self.p_recover = min(max(float(self.p_recover), 0.0), 1.0)
        self.break_scans_required = max(int(self.break_scans_required), 1)
        self.recover_scans_required = max(int(self.recover_scans_required), 1)
        self.beta_jump_threshold = max(float(self.beta_jump_threshold), 0.0)
        self.variance_break_mult = max(float(self.variance_break_mult), 1.0)
        self.disable_cooldown_bars = max(int(self.disable_cooldown_bars), 1)
        self.time_stop_half_life_mult = max(float(self.time_stop_half_life_mult), 0.1)
        self.entry_z = max(float(self.entry_z), 0.1)
        self.exit_z = max(float(self.exit_z), 0.0)

        def _clean_pair(pair: list[str]) -> tuple[str, str]:
            if len(pair) != 2:
                raise ValueError(f"pairs_policy pair must have 2 symbols: {pair}")
            left = str(pair[0]).upper().replace("/", "").strip()
            right = str(pair[1]).upper().replace("/", "").strip()
            if len(left) != 6 or len(right) != 6:
                raise ValueError(f"pairs_policy invalid pair symbol format: {pair}")
            return left, right

        clean_pairs: list[list[str]] = []
        for pair in self.pairs or []:
            left, right = _clean_pair(pair)
            clean_pairs.append([left, right])
        self.pairs = clean_pairs

        clean_groups: dict[str, list[str]] = {}
        for group, symbols in (self.groups or {}).items():
            key = str(group).strip()
            if not key:
                continue
            clean_symbols: list[str] = []
            for symbol in symbols:
                text = str(symbol).upper().replace("/", "").strip()
                if len(text) != 6:
                    raise ValueError(f"pairs_policy invalid symbol in group {group}: {symbol}")
                clean_symbols.append(text)
            clean_groups[key] = clean_symbols
        self.groups = clean_groups

        clean_avoid: list[list[str]] = []
        for pair in self.avoid_pairs or []:
            left, right = _clean_pair(pair)
            clean_avoid.append([left, right])
        self.avoid_pairs = clean_avoid


@dataclass(slots=True)
class RegimeConfig:
    """Regime engine contract."""

    mode: str = "heuristic"
    hmm_lookback_bars: int = 8640
    hmm_retrain_frequency: str = "weekly"
    hmm_n_components: int = 3
    hmm_covariance_type: str = "full"
    hmm_n_iter: int = 200
    hmm_random_state: int = 42
    trend_prob_threshold: float = 0.6
    chop_prob_threshold: float = 0.6
    risk_off_prob_threshold: float = 0.6

    def __post_init__(self) -> None:
        self.mode = str(self.mode).strip().lower()
        if self.mode not in {"heuristic", "hmm"}:
            raise ValueError("regime.mode must be heuristic|hmm")

        self.hmm_lookback_bars = max(int(self.hmm_lookback_bars), 200)
        self.hmm_retrain_frequency = str(self.hmm_retrain_frequency).strip().lower()
        if self.hmm_retrain_frequency not in {"weekly", "daily"}:
            raise ValueError("regime.hmm_retrain_frequency must be weekly|daily")

        self.hmm_n_components = max(int(self.hmm_n_components), 2)
        self.hmm_covariance_type = str(self.hmm_covariance_type).strip().lower()
        if self.hmm_covariance_type not in {"full", "diag", "spherical", "tied"}:
            raise ValueError("regime.hmm_covariance_type must be full|diag|spherical|tied")
        self.hmm_n_iter = max(int(self.hmm_n_iter), 20)
        self.hmm_random_state = int(self.hmm_random_state)

        self.trend_prob_threshold = min(max(float(self.trend_prob_threshold), 0.0), 1.0)
        self.chop_prob_threshold = min(max(float(self.chop_prob_threshold), 0.0), 1.0)
        self.risk_off_prob_threshold = min(max(float(self.risk_off_prob_threshold), 0.0), 1.0)
