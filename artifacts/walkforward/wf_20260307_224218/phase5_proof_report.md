# Phase 5 Proof Report

Run Directory: `artifacts\walkforward\wf_20260307_224218`
Overall Go/No-Go: **NO-GO**

## Cross-Split Summary
| ('mode', '') | ('total_return', 'mean') | ('total_return', 'median') | ('total_return', 'std') | ('sharpe', 'mean') | ('sharpe', 'median') | ('sharpe', 'std') | ('max_drawdown', 'mean') | ('max_drawdown', 'median') | ('max_drawdown', 'std') | ('trades', 'mean') | ('trades', 'median') | ('trades', 'std') |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid | 0.021364 | 0.021364 | nan | 10.30374 | 10.30374 | nan | 0.022709 | 0.022709 | nan | 39.0 | 39.0 | nan |
| pairs_only | 0.0 | 0.0 | nan | 0.0 | 0.0 | nan | 0.0 | 0.0 | nan | 0.0 | 0.0 | nan |
| trend_only | -0.0323 | -0.0323 | nan | -10.733409 | -10.733409 | nan | 0.054389 | 0.054389 | nan | 22.0 | 22.0 | nan |

## Hybrid vs Baselines (Median)
| mode | median_total_return | median_sharpe | median_max_drawdown |
| --- | --- | --- | --- |
| hybrid | 0.0213642786240655 | 10.303740447672087 | 0.0227091802284482 |
| pairs_only | 0.0 | 0.0 | 0.0 |
| trend_only | -0.0323001963291096 | -10.733409318161698 | 0.0543894769500657 |

## Worst Split
Worst split index: `0`
Regime mix={'RISK_OFF': 0.390625, 'TREND': 0.359375, 'CHOP': 0.25}, mean turnover=1.0312, cumulative costs=0.0135, max_dd=0.0227

## Attribution
### PnL by Engine
| engine_source | n_trades | total_pnl | win_rate | pnl_share |
| --- | --- | --- | --- | --- |
| trend | 39 | 0.0351751946078451 | 0.6410256410256411 | 1.0 |

### PnL by Regime
| entry_regime | n_trades | total_pnl | win_rate | pnl_share |
| --- | --- | --- | --- | --- |
| TREND | 39 | 0.0351751946078451 | 0.6410256410256411 | 1.0 |

### PnL by Engine x Regime
| engine_source | entry_regime | n_trades | total_pnl | win_rate | pnl_share_within_engine |
| --- | --- | --- | --- | --- | --- |
| trend | TREND | 39 | 0.0351751946078451 | 0.6410256410256411 | 1.0 |

### Pairs Diagnostics
| pair_id | scan_rows | latest_pvalue | latest_beta | latest_spread_std | latest_z_abs_p95 | state | trade_count | primary_reason | split_idx |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EURUSD-GBPUSD | 1 | nan | nan | nan | nan | WATCH | 0 | insufficient_bars | 0 |
| EURUSD-AUDUSD | 1 | nan | nan | nan | nan | WATCH | 0 | insufficient_bars | 0 |
| GBPUSD-AUDUSD | 1 | nan | nan | nan | nan | WATCH | 0 | insufficient_bars | 0 |
| USDCAD-AUDUSD | 1 | nan | nan | nan | nan | WATCH | 0 | insufficient_bars | 0 |

## Regime QA
| split_idx | n_bars | n_transitions | transitions_per_1000_bars | max_posterior_sum_error | occupancy_trend | occupancy_chop | occupancy_risk_off | posterior_sum_ok | churn_ok | occupancy_ok | regime_qa_pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 64 | 25 | 390.625 | 1.3988810110276972e-14 | 0.359375 | 0.25 | 0.390625 | True | False | True | False |

## Trend Model Traceability
Requested model version: `latest`
Manifest feature schema hash: `a6b42530d54cedf9d854040403fd2d8c654ea9a0f9f7ef8769c0500fcfac31ed`
Observed model versions in metrics: `['in_memory']`
Observed feature schema hashes in metrics: `['a6b42530d54cedf9d854040403fd2d8c654ea9a0f9f7ef8769c0500fcfac31ed']`
Model version consistency check: **PASS**

## Robustness
### Cost Sweep
| scenario | split_idx | commission_bps | slippage_bps | total_return | sharpe | max_drawdown | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | 0 | 1.0 | 1.0 | 0.0213642786240655 | 1.0516211057863722 | 0.0227091802284482 | 0.171875 |
| plus_50 | 0 | 1.5 | 1.5 | 0.0146412064442735 | 0.7385712403954762 | 0.0231979233830525 | 0.171875 |
| plus_100 | 0 | 2.0 | 2.0 | 0.0079606924037618 | 0.4224812954744841 | 0.0236865100850883 | 0.171875 |
| worst_case | 0 | 2.0 | 3.0 | 0.0013224777996598 | 0.1038690306191226 | 0.0241749403580336 | 0.171875 |

### Parameter Sweep
No data.

Positive-return share: 0.00%
Non-negative-Sharpe share: 0.00%
Relative return degradation: 1.0000

## Go/No-Go Checklist
- PASS: hybrid_beats_pairs_only
- PASS: hybrid_beats_trend_only
- PASS: worst_split_drawdown_survivable
- PASS: costs_do_not_kill_edge
- FAIL: attribution_matches_theory
- PASS: pair_profit_concentration_ok
- PASS: trend_model_version_consistent
- FAIL: param_sweep_positive_return_share_ok
- FAIL: param_sweep_sharpe_share_ok
