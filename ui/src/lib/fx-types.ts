// Shared types for FX Hybrid Engine UI

export type ArtifactSource = 'latest_run' | 'run_history' | 'mock' | 'missing';

export interface DataProvenance {
  overall: 'latest_run' | 'run_history' | 'mock' | 'mixed';
  files: Record<string, ArtifactSource>;
}

export interface Candle {
  time: string; // ISO 8601
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  symbol?: string;
}

export interface EquityPoint {
  timestamp: string; // ISO 8601
  equity: number;
  regime_label: 'TREND' | 'CHOP' | 'RISK_OFF';
}

export interface Trade {
  id: string;
  time: string; // ISO 8601 entry
  exit_time: string | null;
  symbol: string;
  engine_source: 'trend' | 'pairs';
  side: 'long' | 'short';
  entry: number;
  exit: number | null;
  stop: number;
  take_profit: number;
  size: number;
  pnl: number;
  pnl_pct: number;
  close_reason: string | null;
  regime_at_entry: 'TREND' | 'CHOP' | 'RISK_OFF';
  tags: string[];
}

export interface DiagnosticEvent {
  category: 'data' | 'execution' | 'risk' | 'orders' | 'exit';
  message: string;
  timestamp: string;
}

export interface RunMetrics {
  sharpe_ratio: number;
  total_return: number;
  max_drawdown: number;
  win_rate: number;
  num_trades: number;
  avg_trade_pnl: number;
}

export interface RunManifest {
  run_id: string;
  wf_run_id?: string;
  started_at: string;
  ended_at: string;
  symbols: string[];
  active_symbol: string;
  regime: 'TREND' | 'CHOP' | 'RISK_OFF';
  regime_probabilities: Record<string, number>;
  status: string;
  data_profile?: string;
  pipeline_version?: string;
  artifact_context?: 'historical_walkforward' | 'paper_strategy' | 'paper_scaffold';
  paper_trading_active?: boolean;
  live_broker?: string | null;
  live_rail?: string | null;
  broker_order_routing?: string;
  strategy_status?: string | null;
  data_source?: string;
  simulated_market_data?: boolean;
  git_commit?: string;
  config_hash?: string;
  schema_version?: string;
  daily_pnl?: number;
  daily_pnl_pct?: number;
  weekly_pnl?: number;
  weekly_pnl_pct?: number;
  close_only?: boolean;
  ladder_stage?: string;
  gross_exposure_pct?: number;
  errors: DiagnosticEvent[];
  warnings: DiagnosticEvent[];
  notes: string[];
  metrics?: RunMetrics;
}

export interface RunResult {
  status: 'success' | 'error';
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_ms: number;
}

export interface RegimePosterior {
  timestamp: string;
  regime_label: 'TREND' | 'CHOP' | 'RISK_OFF';
  TREND: number;
  CHOP: number;
  RISK_OFF: number;
}

export interface EngineAllocation {
  timestamp: string;
  pairs_alloc: number;
  trend_alloc: number;
  total_alloc: number;
  regime_label: 'TREND' | 'CHOP' | 'RISK_OFF';
}

export interface PairDiagnostic {
  pair_id: string;
  state: 'TRADABLE' | 'WATCH' | 'DISABLED';
  trade_count: number;
  primary_reason: string;
  latest_pvalue: number | null;
  latest_beta: number | null;
  latest_spread_std: number | null;
  latest_z_abs_p95: number | null;
  split_idx: number;
  in_trade_universe?: boolean;
}

export interface WfSplitMetrics {
  split_idx: number;
  total_return: number;
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  trades: number;
}

export interface WalkforwardMetrics {
  splits_meta: Record<string, string>[];
  by_mode: Record<string, WfSplitMetrics[]>;
}

export interface PnlAttributionRow {
  engine_source?: string;
  entry_regime?: string;
  n_trades?: number;
  total_pnl?: number;
  win_rate?: number;
  pnl_share?: number;
  pnl_share_within_engine?: number;
  [key: string]: unknown;
}

export interface PnlAttribution {
  engine_x_regime: PnlAttributionRow[];
  by_engine: PnlAttributionRow[];
  by_regime: PnlAttributionRow[];
}

export interface ProofCheck {
  value: number | null;
  threshold: number | null;
  pass: boolean;
}

export interface ProofChecks {
  pass: boolean;
  checks: Record<string, ProofCheck>;
  engine_abs_pnl: Record<string, number>;
}

export interface RobustnessRow {
  scenario: string;
  commission_bps: number;
  slippage_bps: number;
  total_return: number;
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
}

export interface Robustness {
  cost_sweep: RobustnessRow[];
  param_sweep: Record<string, unknown>[];
  diagnostics: Record<string, unknown>;
}

export interface PromotionDecision {
  pass: boolean;
  checks: Record<string, boolean>;
  failed_reasons: string[];
  incident_counts: Record<string, number>;
  ops_summary: Record<string, unknown>;
  ladder: { action: string; current_stage: string; next_stage: string };
}

export interface FeatureImportance {
  feature: string;
  mean_abs_shap: number;
}

export interface ConfidenceBucket {
  bucket: string;
  win_rate: number;
  n: number;
  avg_confidence: number;
}

export interface RegimeAccuracy {
  win_rate: number;
  n: number;
  avg_pnl: number;
}

export interface TradeAnalyticsRow {
  trade_id: string;
  symbol: string;
  engine: string;
  entry_efficiency: number | null;
  adverse_excursion: number | null;
  favorable_excursion: number | null;
  signal_type: string | null;
  exit_reason: string | null;
  trigger_tags: string[];
}

export interface TradeAnalysis {
  n_trades: number;
  n_features: number;
  feature_importance: FeatureImportance[];
  confidence_buckets: ConfidenceBucket[];
  regime_accuracy: Record<string, RegimeAccuracy>;
  model_score: { accuracy: number; auc: number };
  top_features: string[];
  trade_analytics_rows?: TradeAnalyticsRow[];
}

export interface SignalRow {
  timestamp: string;
  symbol: string;
  direction: 'long' | 'short' | 'flat';
  size: number;
  engine_source: string;
  confidence: number;
  regime_label: string;
  trend_p_up: number;
  trend_p_down: number;
  decision_threshold?: number;
  trend_model_version?: string;
  decision_reason?: string;
}

export interface PairScanPoint {
  date: string;
  pvalue: number | null;
  beta: number | null;
  spread_std: number | null;
  z_abs_p95: number | null;
  state: string;
}

export interface PairZScorePoint {
  date: string;
  zscore: number;
}

export interface PairStateEvent {
  date: string;
  event: string;
  reason: string;
}

export interface PairHistory {
  in_trade_universe?: boolean;
  scan_history: PairScanPoint[];
  zscore_series: PairZScorePoint[];
  state_events: PairStateEvent[];
}

export interface IndicatorSnapshot {
  timestamp: string;
  symbol: string;
  close: number;
  sma_fast: number | null;
  sma_slow: number | null;
  rsi: number | null;
  realized_vol: number | null;
  momentum_slope: number | null;
  sma_crossover: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  macd_bullish_divergence: boolean;
  macd_bearish_divergence: boolean;
}

export interface TrendDecision {
  timestamp: string;
  symbol: string;
  direction: 'long' | 'short' | 'flat';
  confidence: number;
  regime_label: string;
  trend_p_up: number;
  trend_p_down: number;
  decision_threshold: number;
  decision_reason: string;
  trend_model_version: string;
  rsi: number | null;
  realized_vol: number | null;
  sma_crossover: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  observed_divergence: 'none' | 'bullish' | 'bearish';
}

export interface BrokerContextPosition {
  symbol: string;
  quantity: number;
}

export interface BrokerContextSummary {
  provider?: string;
  available: boolean;
  connection_status: string;
  account_number: string | null;
  symbol_map_ready_count?: number;
  symbol_map_missing?: string[];
  positions_count?: number;
  open_orders_count?: number;
  accounts_count?: number;
  balances?: Record<string, unknown> | null;
  positions?: BrokerContextPosition[];
  open_orders?: Record<string, unknown>[];
  error?: string | null;
}

export interface NoTradeSummary {
  signals_emitted?: number;
  fills_emitted?: number;
  closed_trades?: number;
  observed_pair_count?: number;
  tradable_pair_count?: number;
  pair_reason_counts?: Record<string, number>;
  trend_confidence_misses?: number;
  trend_feature_unavailable?: number;
  close_only_active?: boolean;
  missing_bars_count?: number;
  symbol_map_missing_count?: number;
  regime_distribution?: Record<string, number>;
}

export interface PaperStrategySummary {
  status?: string;
  execution_window_start?: string;
  execution_window_end?: string;
  data_source?: string;
  bar_frequency?: string;
  simulated_market_data?: boolean;
  broker_order_routing?: string;
  symbols?: string[];
  bars_written?: number;
  signals_emitted?: number;
  fills_emitted?: number;
  closed_trades?: number;
  last_regime?: string;
  last_equity?: number | null;
  position_plan_count?: number;
  active_position_count?: number;
  contract_ready_position_count?: number;
  safety_summary?: Record<string, unknown>;
  metrics?: RunMetrics;
  broker_context?: BrokerContextSummary;
  no_trade_diagnostics?: NoTradeSummary;
}

export interface RunCatalogEntry {
  run_id: string;
  started_at: string | null;
  ended_at: string | null;
  status: string;
  strategy_status: string | null;
  artifact_context: 'paper_strategy' | 'paper_scaffold';
  symbols: string[];
  last_regime: string | null;
  signal_count: number;
  fill_count: number;
  trade_count: number;
  close_only: boolean;
  data_source: string | null;
  live_broker: string | null;
  live_rail: string | null;
  broker_order_routing: string | null;
  broker_context: BrokerContextSummary | null;
}

export interface RunContext {
  requested_run_id: string | null;
  effective_run_id: string | null;
  requested_run_found: boolean;
  fallback_applied: boolean;
}

export interface RunsResponse {
  runs: RunCatalogEntry[];
}

export interface OpsEvent {
  timestamp: string;
  event_type:
    | 'regime_transition'
    | 'breaker_trigger'
    | 'pair_disable'
    | 'pair_enable'
    | 'signal_reject'
    | 'stale_data'
    | 'deploy_change'
    | 'close_only_engage'
    | 'close_only_disengage'
    | 'risk_event';
  message: string;
  symbols?: string[];
  action?: string;
  reason_code?: string;
}

export interface TrendModelMeta {
  model_version: string;
  training_window_days: number;
  feature_schema_hash: string;
  last_retrain_time: string;
  calibration_score: number | null;
  feature_columns: string[];
  label_mode: string;
  label_horizon_bars: number;
  label_threshold_bps: number;
}

export interface AlgoState {
  manifest: RunManifest;
  trades: Trade[];
  candles: Candle[];
  equity_curve: EquityPoint[];
  events: OpsEvent[];
  run_context: RunContext;
  source: DataProvenance['overall'];
  provenance: DataProvenance;
  log_available: boolean;
}

export interface RegimeResponse {
  run_context: RunContext;
  source: DataProvenance['overall'];
  provenance: DataProvenance;
  regime_posteriors: RegimePosterior[];
  engine_allocations: EngineAllocation[];
}

export interface WalkforwardResponse {
  source: DataProvenance['overall'];
  provenance: DataProvenance;
  walkforward_metrics: WalkforwardMetrics | null;
  pnl_attribution: PnlAttribution | null;
  proof_checks: ProofChecks | null;
  promotion_decision: PromotionDecision | null;
  robustness: Robustness | null;
  risk_events: OpsEvent[];
}

export interface PairsResponse {
  run_context: RunContext;
  source: DataProvenance['overall'];
  provenance: DataProvenance;
  pairs: PairDiagnostic[];
  pair_history: Record<string, PairHistory>;
}

export interface AnalysisResponse {
  run_context: RunContext;
  source: DataProvenance['overall'];
  provenance: DataProvenance;
  analysis: TradeAnalysis | null;
  signals_sample: SignalRow[];
  trend_model_meta: TrendModelMeta | null;
  trend_decisions: TrendDecision[];
  indicator_snapshots: IndicatorSnapshot[];
}

export interface PaperOpsState {
  run_context: RunContext;
  source: DataProvenance['overall'];
  provenance: DataProvenance;
  run_manifest: {
    run_id: string;
    git_commit: string;
    config_hash: string;
    schema_version: string;
    created_at_utc: string;
    seed: number;
    precompute_enabled: boolean;
    mode_reuse_enabled: boolean;
    data_profile: string;
    pipeline_version: string;
    live_broker?: string | null;
    live_rail?: string | null;
    broker_order_routing?: string;
    strategy_status?: string;
    data_source?: string;
    simulated_market_data?: boolean;
  };
  stale_data_count: number;
  missing_bars_count: number;
  orders_per_hour: number;
  reject_rate: number;
  last_bars: Array<{ timestamp: string; symbol: string; close: number }>;
  objectstore_status: string;
  broker_context?: BrokerContextSummary | null;
  strategy_summary?: PaperStrategySummary | null;
  no_trade_summary?: NoTradeSummary | null;
}
