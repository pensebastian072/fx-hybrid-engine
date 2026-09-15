# Operations Runbook

## Scope
This runbook covers Phase 6 paper/live operational controls:
- append-only data capture
- health gating (`close_only`)
- reconciliation and recovery
- strict completion precheck (`fxhe-phase6-precheck`)

## Start
1. Prepare config and runtime environment.
2. Create a unique run directory under the chosen ops root, for example `outputs/paper/YYYY-MM-DD/<run_id>/`.
3. Initialize metadata artifacts:
   - `run_manifest.json`
   - `config_snapshot.yaml`
4. Start the trading loop with health checks enabled before each decision cycle.
5. Run strict gate validation:
   - `fxhe-phase6-precheck --run-dir <run_dir>`
6. For promotion readiness against latest proof:
   - `fxhe-promote-check --wf-id <wf_run_id> --paper-run-dir <run_dir>`
7. Before any live deployment:
   - `fxhe-live-precheck`
8. Start the configured live rail:
   - `fxhe-live --paper`

For a Tastytrade rail, set `live_execution.broker=tastytrade`, provide the OAuth env vars named in `tastytrade.*_env`, and fill `tastytrade.symbol_map` before starting the session. If `live_execution.rail=tastytrade_live`, explicitly set `live_execution.enable_broker_native_orders=true` and `live_execution.enable_broker_market_data=true`; both flags default to false and precheck/CLI will block native routing until they are enabled. The current paper implementation writes a broker-ready position plan and safety snapshot alongside the append-only streams so you can verify the latest desired state before enabling broker-native routing.

## Data Artifacts
Append-only streams expected per run:
- `bars.parquet`
- `features.parquet`
- `signals.parquet`
- `targets.parquet`
- `orders.parquet`
- `fills.parquet`
- `equity_curve.parquet`
- `risk_events.parquet`
- `broker_events.jsonl`
- `reconciliation_events.jsonl`
- `ops_summary.json`

Helpful paper-session snapshots:
- `paper_trades.json`
- `paper_position_plan.json`
- `paper_strategy_summary.json`
- `paper_safety_summary.json`

Broker-native live snapshots (when `live_execution.rail=tastytrade_live` and both native flags are enabled):
- `broker_native_summary.json`

Do not overwrite prior rows. Always append new records with timestamps.

## Health Procedure
Evaluate health each loop:
1. Check last bar staleness against policy threshold.
2. Check broker reject count against policy threshold.
3. If unhealthy, set `close_only=True`:
   - allow exits only
   - block new entries
   - append a broker/health event

## Reconciliation Procedure
On each cycle (or fixed cadence), compare expected vs actual:
1. Holdings by symbol and quantity.
2. Open order IDs.

Reconciliation must emit explicit provenance:
1. `reconciliation_mode` (`broker_validated`, `simulated`, or `skipped`).
2. `reconciliation_status` (for example `evaluated` or `skipped`).
3. `reconciliation_reason` when not broker-validated.

If mismatch is detected:
1. Pause new entries immediately.
2. Attempt reconciliation/repair.
3. If unresolved, execute emergency flatten policy (if enabled).

Local-paper note:
1. If broker state is unavailable, reconciliation may be `skipped`, but this must be explicit in artifacts and events.
2. Skipped local-paper reconciliation is treated as non-failure by promotion incident counting.
3. Unresolved non-skipped reconciliation incidents remain promotion blockers.

## Stop
1. Set strategy to close-only and wait for exits, or flatten immediately per emergency policy.
2. Confirm no open positions and no open orders.
3. Append final risk/broker events.
4. Persist terminal equity and process exit status.

## Emergency Flatten Checklist
1. Enable close-only gate.
2. Cancel all open orders.
3. Submit flatten orders for all non-zero holdings.
4. Reconcile until holdings and orders are both flat.
5. Record incident summary in `broker_events.jsonl` and postmortem notes.

## Known Failure Modes
1. Data feed staleness or missing bars.
2. Broker disconnect/reject spikes.
3. Persistent holdings/order reconciliation mismatch.
4. Circuit-breaker threshold breaches on daily/weekly losses.
5. Excessive volatility requiring exposure throttle.

## Daily Monitoring Checklist
1. Confirm latest `heartbeat` and `session_start`/`session_stop` events in `broker_events.jsonl`.
2. Confirm no unresolved `flatten_required` states.
3. Confirm `risk_events.parquet` does not contain unresolved critical breakers.
4. Confirm append-audit (`write_audit.jsonl`) remains monotonic.
5. Re-run `fxhe-phase6-precheck` after any incident before re-enabling entries.
6. Confirm `paper_safety_summary.json` includes explicit `reconciliation_mode` and `reconciliation_status` for local paper runs.
