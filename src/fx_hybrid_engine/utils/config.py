"""Config loading and validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PairsConfig:
    pairs: list[list[str]]
    cointegration_pvalue_threshold: float = 0.05
    cointegration_method: str = "engle_granger"  # "engle_granger" | "johansen"
    spread_window: int = 60
    entry_zscore: float = 2.0
    exit_zscore: float = 1.0
    max_position_pct: float = 0.10


@dataclass
class TrendConfig:
    feature_lookback: int = 20
    signal_threshold: float = 0.70
    decision_threshold: float | None = 0.70
    sma_fast: int = 50
    sma_slow: int = 200
    model_path: str = "config/trend_model.pkl"
    model_root: str = "models/trend"
    model_version: str = "latest"
    label_horizon_bars: int = 8
    label_threshold_bps: float = 6.0
    min_train_rows: int = 1200
    class_weight: str = "balanced"
    train_window_days: int = 270
    test_window_days: int = 60
    step_days: int = 30


@dataclass
class MLSignalConfig:
    """Config for the ML ensemble signal engine (RandomForest + XGBoost)."""
    label_horizon_bars: int = 8
    label_threshold_bps: float = 6.0
    min_train_rows: int = 500
    n_estimators: int = 200
    max_depth: int = 4
    class_weight: str = "balanced"
    decision_threshold: float = 0.55
    use_xgboost: bool = True           # stack RF + XGBoost; falls back to RF only
    use_advanced_features: bool = True # include Bollinger, MACD, ATR, etc.
    bb_window: int = 20
    macd_fast: int = 12
    macd_slow: int = 26
    model_root: str = "models/ml_ensemble"
    model_version: str = "latest"
    seed: int = 42


@dataclass
class RegimeConfig:
    n_states: int = 3
    obs_window: int = 30
    vol_window: int = 20
    model_path: str = "config/hmm_model.pkl"
    state_labels: dict[int, str] = field(default_factory=lambda: {0: "TREND", 1: "CHOP", 2: "RISK_OFF"})


@dataclass
class RiskConfig:
    max_leverage: float = 3.0
    stop_loss_pct: float = 0.02
    drawdown_kill_pct: float = 0.05
    vol_target_annual: float = 0.15
    risk_off_size_multiplier: float = 0.25


@dataclass
class DataConfig:
    source: str = "lean_history"
    bar_frequency: str = "15m"
    history_years: int = 10
    openbb_provider: str = "fmp"


@dataclass
class WalkforwardConfig:
    train_window_days: int = 365
    test_window_days: int = 90
    step_days: int = 30
    max_splits: int | None = None
    output_root: str = "artifacts/walkforward"
    backend: str = "local"  # local | lean | both
    data_profile: str = "local_smoke"  # local_smoke | openbb
    start_date: str = "2018-01-01"
    end_date: str = "2024-12-31"
    auto_report: bool = True


@dataclass
class ExecutionCostsConfig:
    commission_bps: float = 1.0
    slippage_bps: float = 1.0


@dataclass
class RobustnessConfig:
    cost_scenarios: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"name": "base", "commission_mult": 1.0, "slippage_mult": 1.0},
            {"name": "plus_50", "commission_mult": 1.5, "slippage_mult": 1.5},
            {"name": "plus_100", "commission_mult": 2.0, "slippage_mult": 2.0},
            {"name": "worst_case", "commission_mult": 2.0, "slippage_mult": 3.0},
        ]
    )
    param_sweep_samples: int = 8
    pairs_zscore_jitter_pct: float = 0.15
    cointegration_jitter_pct: float = 0.15
    trend_threshold_jitter_abs: float = 0.05
    risk_cap_jitter_pct: float = 0.10
    random_seed: int = 42


@dataclass
class ProofGatesConfig:
    min_trend_pnl_in_trend_share: float = 0.60
    min_pairs_pnl_in_chop_share: float = 0.60
    max_risk_off_pnl_share_abs: float = 0.10
    max_pair_profit_concentration: float = 0.50
    max_worst_split_drawdown: float = 0.25
    min_positive_param_sweep_share: float = 0.50
    min_non_negative_sharpe_param_sweep_share: float = 0.50


@dataclass
class PairsPolicyConfig:
    scan_enabled: bool = True
    scan_frequency_bars: int = 480
    min_train_bars: int = 1000
    p_enter: float = 0.08
    p_exit: float = 0.15
    p_break: float = 0.25
    p_recover: float = 0.10
    break_scans_required: int = 2
    spread_std_spike_k: float = 2.5
    beta_jump_abs: float = 0.30
    max_holding_bars: int = 288
    cooldown_scans: int = 2


@dataclass
class RegimeQAConfig:
    enabled: bool = True
    max_churn_per_1000_bars: float = 120.0
    max_posterior_sum_error: float = 1e-6
    min_state_occupancy_share: float = 0.02


@dataclass
class RegimeCompareConfig:
    enabled: bool = False
    policies: list[str] = field(default_factory=lambda: ["hmm", "heuristic", "none"])
    heuristic_vol_z_risk_off: float = 1.5
    heuristic_mom_z_trend: float = 0.5
    heuristic_vol_z_trend_max: float = 1.0


@dataclass
class OpsConfig:
    output_root: str = "outputs"
    legacy_output_root: str = "artifacts/ops"
    mode: str = "paper"
    strict_append_audit: bool = True
    require_run_id_columns: bool = True


@dataclass
class HealthMonitorConfig:
    state_machine_thresholds: dict[str, float] = field(
        default_factory=lambda: {
            "data_stale_seconds": 300.0,
            "degraded_rejects": 3.0,
            "broker_down_rejects": 8.0,
        }
    )


@dataclass
class ReconciliationConfig:
    enabled: bool = True
    interval_seconds: int = 60
    qty_tolerance: float = 1e-8
    auto_flatten_on_persistent_mismatch: bool = False
    persistent_mismatch_cycles: int = 3


@dataclass
class CircuitBreakersConfig:
    daily_loss_limit: float = 0.03
    weekly_loss_limit: float = 0.06
    max_consecutive_losses: int = 5
    vol_spike_threshold: float = 2.5
    reject_spike_threshold: int = 5
    symbol_cooldown_minutes: int = 60


@dataclass
class LadderStageConfig:
    exposure_multiplier: float = 0.25
    loss_limit_multiplier: float = 0.50


@dataclass
class MicroLiveLadderConfig:
    active_stage: str = "stage0_paper"
    universe_policy: str = "always_full"
    stage0_paper: LadderStageConfig = field(
        default_factory=lambda: LadderStageConfig(exposure_multiplier=0.10, loss_limit_multiplier=0.40)
    )
    stage1_micro: LadderStageConfig = field(
        default_factory=lambda: LadderStageConfig(exposure_multiplier=0.25, loss_limit_multiplier=0.50)
    )
    stage2_small: LadderStageConfig = field(
        default_factory=lambda: LadderStageConfig(exposure_multiplier=0.60, loss_limit_multiplier=0.75)
    )
    stage3_scale: LadderStageConfig = field(
        default_factory=lambda: LadderStageConfig(exposure_multiplier=1.00, loss_limit_multiplier=1.00)
    )
    # legacy aliases kept for backward compatibility in old configs/tests
    stage_1: LadderStageConfig = field(
        default_factory=lambda: LadderStageConfig(exposure_multiplier=0.25, loss_limit_multiplier=0.50)
    )
    stage_2: LadderStageConfig = field(
        default_factory=lambda: LadderStageConfig(exposure_multiplier=0.60, loss_limit_multiplier=0.75)
    )
    stage_3: LadderStageConfig = field(
        default_factory=lambda: LadderStageConfig(exposure_multiplier=1.00, loss_limit_multiplier=1.00)
    )


@dataclass
class WeeklyEvaluationConfig:
    enabled: bool = True
    schedule_hint: str = "0 6 * * 1"
    profile: str = "local_smoke"
    max_splits: int = 1
    run_robustness: bool = False


@dataclass
class ModelRegistryConfig:
    root: str = "artifacts/model_registry"
    trend_refresh_days: int = 7
    hmm_refresh_days: int = 7
    pairs_refresh_days: int = 1


@dataclass
class AlertsConfig:
    enabled: bool = True
    output_path: str = "alerts.jsonl"
    min_severity: str = "warning"


@dataclass
class LiveExecutionConfig:
    rail: str = "qc_paper"
    broker: str = "quantconnect"
    enable_broker_native_orders: bool = False
    enable_broker_market_data: bool = False


@dataclass
class QCRuntimeConfig:
    enabled: bool = True
    resolution: str = "15m"
    state_store_namespace: str = "fxhe"
    health_check_interval_seconds: int = 60
    reconcile_interval_seconds: int = 60
    order_reject_lookback: int = 20
    cancel_on_close_only: bool = False


@dataclass
class PromotionConfig:
    paper_window_days: int = 14
    max_rejects_in_window: int = 10
    max_stale_events_in_window: int = 5
    max_reconcile_failures_in_window: int = 3
    require_attribution_gate: bool = True
    require_cost_gate: bool = True
    require_drawdown_gate: bool = True


@dataclass
class LivePrecheckConfig:
    required_env_vars: list[str] = field(default_factory=lambda: ["QC_USER_ID", "QC_API_TOKEN"])
    extra_required_env_vars: list[str] = field(default_factory=list)
    require_emergency_flatten: bool = True
    ladder_config_path: str = "config/ladder.yaml"


@dataclass
class TastytradeConfig:
    api_base_url: str = "https://api.tastytrade.com"
    oauth_token_url: str = "https://api.tastytrade.com/oauth2/token"
    accounts_url: str = "https://api.tastytrade.com/customers/me/accounts"
    balances_url_template: str = "https://api.tastytrade.com/accounts/{account_number}/balances"
    client_id_env: str = "TASTYTRADE_CLIENT_ID"
    client_secret_env: str = "TASTYTRADE_CLIENT_SECRET"
    refresh_token_env: str = "TASTYTRADE_REFRESH_TOKEN"
    account_number_env: str = "TASTYTRADE_ACCOUNT_NUMBER"
    validate_api_on_precheck: bool = True
    require_account_number: bool = False
    require_symbol_map: bool = True
    symbol_map: dict[str, str] = field(default_factory=dict)


@dataclass
class FrictionModelConfig:
    commission_bps: float = 1.0
    slippage_bps: float = 1.0
    spread_bps_proxy: float = 0.5


@dataclass
class EngineConfig:
    universe: dict[str, Any]
    pairs: PairsConfig
    trend: TrendConfig
    regime: RegimeConfig
    risk: RiskConfig
    data: DataConfig
    walkforward: WalkforwardConfig = field(default_factory=WalkforwardConfig)
    execution_costs: ExecutionCostsConfig = field(default_factory=ExecutionCostsConfig)
    robustness: RobustnessConfig = field(default_factory=RobustnessConfig)
    proof_gates: ProofGatesConfig = field(default_factory=ProofGatesConfig)
    pairs_policy: PairsPolicyConfig = field(default_factory=PairsPolicyConfig)
    regime_qa: RegimeQAConfig = field(default_factory=RegimeQAConfig)
    regime_compare: RegimeCompareConfig = field(default_factory=RegimeCompareConfig)
    ops: OpsConfig = field(default_factory=OpsConfig)
    health_monitor: HealthMonitorConfig = field(default_factory=HealthMonitorConfig)
    reconciliation: ReconciliationConfig = field(default_factory=ReconciliationConfig)
    circuit_breakers: CircuitBreakersConfig = field(default_factory=CircuitBreakersConfig)
    micro_live_ladder: MicroLiveLadderConfig = field(default_factory=MicroLiveLadderConfig)
    weekly_evaluation: WeeklyEvaluationConfig = field(default_factory=WeeklyEvaluationConfig)
    model_registry: ModelRegistryConfig = field(default_factory=ModelRegistryConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    live_execution: LiveExecutionConfig = field(default_factory=LiveExecutionConfig)
    qc_runtime: QCRuntimeConfig = field(default_factory=QCRuntimeConfig)
    promotion: PromotionConfig = field(default_factory=PromotionConfig)
    live_precheck: LivePrecheckConfig = field(default_factory=LivePrecheckConfig)
    tastytrade: TastytradeConfig = field(default_factory=TastytradeConfig)
    friction_model: FrictionModelConfig = field(default_factory=FrictionModelConfig)

    @property
    def pair_list(self) -> list[list[str]]:
        return self.universe.get("pair_trade_universe", self.universe.get("pairs", []))

    @property
    def trend_symbols(self) -> list[str]:
        return self.universe.get("trend_symbols", [])

    @property
    def pair_observe_symbols(self) -> list[str]:
        configured = self.universe.get("pair_observe_universe")
        if isinstance(configured, list) and configured:
            return [str(symbol) for symbol in configured]
        observed = sorted({s for pair in self.pair_list for s in pair} | set(self.trend_symbols))
        return observed

    @property
    def pair_observe_list(self) -> list[list[str]]:
        symbols = self.pair_observe_symbols
        return [list(pair) for pair in combinations(symbols, 2)]


def load_config(path: str | Path) -> EngineConfig:
    """Load and parse YAML config file into EngineConfig."""
    with open(path) as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    pairs_raw = raw.get("pairs_engine", {})
    trend_raw = raw.get("trend_engine", {})
    regime_raw = raw.get("regime", {})
    risk_raw = raw.get("risk", {})
    data_raw = raw.get("data", {})
    walkforward_raw = raw.get("walkforward", {})
    execution_costs_raw = raw.get("execution_costs", {})
    robustness_raw = raw.get("robustness", {})
    proof_gates_raw = raw.get("proof_gates", {})
    pairs_policy_raw = raw.get("pairs_policy", {})
    regime_qa_raw = raw.get("regime_qa", {})
    regime_compare_raw = raw.get("regime_compare", {})
    ops_raw = raw.get("ops", {})
    health_monitor_raw = raw.get("health_monitor", {})
    reconciliation_raw = raw.get("reconciliation", {})
    circuit_breakers_raw = raw.get("circuit_breakers", {})
    micro_live_ladder_raw = raw.get("micro_live_ladder", {})
    weekly_evaluation_raw = raw.get("weekly_evaluation", {})
    model_registry_raw = raw.get("model_registry", {})
    alerts_raw = raw.get("alerts", {})
    live_execution_raw = raw.get("live_execution", {})
    qc_runtime_raw = raw.get("qc_runtime", {})
    promotion_raw = raw.get("promotion", {})
    live_precheck_raw = raw.get("live_precheck", {})
    tastytrade_raw = raw.get("tastytrade", {})
    friction_model_raw = raw.get("friction_model", {})
    universe = raw.get("universe", {})

    # state_labels keys must be int
    if "state_labels" in regime_raw:
        regime_raw["state_labels"] = {int(k): v for k, v in regime_raw["state_labels"].items()}
    if tastytrade_raw.get("symbol_map") is None:
        tastytrade_raw["symbol_map"] = {}

    pairs_raw["pairs"] = universe.get("pair_trade_universe", universe.get("pairs", []))

    ladder_stage_1_raw = micro_live_ladder_raw.get("stage_1", {})
    ladder_stage_2_raw = micro_live_ladder_raw.get("stage_2", {})
    ladder_stage_3_raw = micro_live_ladder_raw.get("stage_3", {})
    ladder_stage0_raw = micro_live_ladder_raw.get("stage0_paper", {})
    ladder_stage1_raw = micro_live_ladder_raw.get("stage1_micro", {})
    ladder_stage2_raw = micro_live_ladder_raw.get("stage2_small", {})
    ladder_stage3_raw = micro_live_ladder_raw.get("stage3_scale", {})

    stage0 = LadderStageConfig(**ladder_stage0_raw) if ladder_stage0_raw else LadderStageConfig(exposure_multiplier=0.10, loss_limit_multiplier=0.40)
    stage1 = LadderStageConfig(**ladder_stage1_raw) if ladder_stage1_raw else (
        LadderStageConfig(**ladder_stage_1_raw) if ladder_stage_1_raw else LadderStageConfig(exposure_multiplier=0.25, loss_limit_multiplier=0.50)
    )
    stage2 = LadderStageConfig(**ladder_stage2_raw) if ladder_stage2_raw else (
        LadderStageConfig(**ladder_stage_2_raw) if ladder_stage_2_raw else LadderStageConfig(exposure_multiplier=0.60, loss_limit_multiplier=0.75)
    )
    stage3 = LadderStageConfig(**ladder_stage3_raw) if ladder_stage3_raw else (
        LadderStageConfig(**ladder_stage_3_raw) if ladder_stage_3_raw else LadderStageConfig(exposure_multiplier=1.00, loss_limit_multiplier=1.00)
    )

    active_stage = micro_live_ladder_raw.get("active_stage", "stage0_paper")
    if active_stage == "stage_1":
        active_stage = "stage1_micro"
    elif active_stage == "stage_2":
        active_stage = "stage2_small"
    elif active_stage == "stage_3":
        active_stage = "stage3_scale"

    return EngineConfig(
        universe=universe,
        pairs=PairsConfig(**pairs_raw),
        trend=TrendConfig(**trend_raw),
        regime=RegimeConfig(**regime_raw),
        risk=RiskConfig(**risk_raw),
        data=DataConfig(**data_raw),
        walkforward=WalkforwardConfig(**walkforward_raw),
        execution_costs=ExecutionCostsConfig(**execution_costs_raw),
        robustness=RobustnessConfig(**robustness_raw),
        proof_gates=ProofGatesConfig(**proof_gates_raw),
        pairs_policy=PairsPolicyConfig(**pairs_policy_raw),
        regime_qa=RegimeQAConfig(**regime_qa_raw),
        regime_compare=RegimeCompareConfig(**regime_compare_raw),
        ops=OpsConfig(**ops_raw),
        health_monitor=HealthMonitorConfig(**health_monitor_raw),
        reconciliation=ReconciliationConfig(**reconciliation_raw),
        circuit_breakers=CircuitBreakersConfig(**circuit_breakers_raw),
        micro_live_ladder=MicroLiveLadderConfig(
            active_stage=active_stage,
            universe_policy=micro_live_ladder_raw.get("universe_policy", "always_full"),
            stage0_paper=stage0,
            stage1_micro=stage1,
            stage2_small=stage2,
            stage3_scale=stage3,
            stage_1=stage1,
            stage_2=stage2,
            stage_3=stage3,
        ),
        weekly_evaluation=WeeklyEvaluationConfig(**weekly_evaluation_raw),
        model_registry=ModelRegistryConfig(**model_registry_raw),
        alerts=AlertsConfig(**alerts_raw),
        live_execution=LiveExecutionConfig(**live_execution_raw),
        qc_runtime=QCRuntimeConfig(**qc_runtime_raw),
        promotion=PromotionConfig(**promotion_raw),
        live_precheck=LivePrecheckConfig(**live_precheck_raw),
        tastytrade=TastytradeConfig(**tastytrade_raw),
        friction_model=FrictionModelConfig(**friction_model_raw),
    )
