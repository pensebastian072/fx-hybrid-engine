# Phase 5 Proof Report

Run Directory: `artifacts\walkforward\manual_smoke3`
Overall Go/No-Go: **NO-GO**

## Cross-Split Summary
| ('mode', '') | ('total_return', 'mean') | ('total_return', 'median') | ('total_return', 'std') | ('sharpe', 'mean') | ('sharpe', 'median') | ('sharpe', 'std') | ('max_drawdown', 'mean') | ('max_drawdown', 'median') | ('max_drawdown', 'std') | ('trades', 'mean') | ('trades', 'median') | ('trades', 'std') |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid | 0.00385 | 0.00385 | 0.005445 | 0.649731 | 0.649731 | 0.918859 | 0.001843 | 0.001843 | 0.002606 | 4.0 | 4.0 | 5.656854 |
| pairs_only | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| trend_only | 0.00121 | 0.00121 | 0.001711 | 0.120565 | 0.120565 | 0.170505 | 0.007295 | 0.007295 | 0.010317 | 4.0 | 4.0 | 5.656854 |

## Hybrid vs Baselines (Median)
| mode | median_total_return | median_sharpe | median_max_drawdown |
| --- | --- | --- | --- |
| hybrid | 0.0038499838546114 | 0.6497310818747545 | 0.00184254338101145 |
| pairs_only | 0.0 | 0.0 | 0.0 |
| trend_only | 0.0012101160979808 | 0.1205651217944475 | 0.0072951071555941 |

## Worst Split
Worst split index: `1`
Regime mix={'RISK_OFF': 1.0}, mean turnover=0.0000, cumulative costs=0.0000, max_dd=0.0000

## Attribution
### PnL by Engine
| engine_source | n_trades | total_pnl | win_rate | pnl_share |
| --- | --- | --- | --- | --- |
| trend | 8 | 0.0109251251384714 | 0.625 | 1.0 |

### PnL by Regime
| entry_regime | n_trades | total_pnl | win_rate | pnl_share |
| --- | --- | --- | --- | --- |
| TREND | 8 | 0.0109251251384714 | 0.625 | 1.0 |

### PnL by Engine x Regime
| engine_source | entry_regime | n_trades | total_pnl | win_rate | pnl_share_within_engine |
| --- | --- | --- | --- | --- | --- |
| trend | TREND | 8 | 0.0109251251384714 | 0.625 | 1.0 |

## Robustness
### Cost Sweep
| scenario | split_idx | commission_bps | slippage_bps | total_return | sharpe | max_drawdown | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base | 0 | 1.0 | 1.0 | 0.0076999677092228 | 1.299462163749509 | 0.0036850867620229 | 0.046875 |
| base | 1 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| plus_50 | 0 | 1.5 | 1.5 | 0.006088232335687 | 1.033116205262586 | 0.0042829952757162 | 0.046875 |
| plus_50 | 1 | 1.5 | 1.5 | 0.0 | 0.0 | 0.0 | 0.0 |
| plus_100 | 0 | 2.0 | 2.0 | 0.0044787932359935 | 0.764133568614714 | 0.0048806645303036 | 0.03125 |
| plus_100 | 1 | 2.0 | 2.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| worst_case | 0 | 2.0 | 3.0 | 0.0028716475338523 | 0.4939208099208084 | 0.0054780945736655 | 0.03125 |
| worst_case | 1 | 2.0 | 3.0 | 0.0 | 0.0 | 0.0 | 0.0 |

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
- FAIL: param_sweep_positive_return_share_ok
- FAIL: param_sweep_sharpe_share_ok
