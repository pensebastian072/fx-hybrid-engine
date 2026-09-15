# Local LEAN FX Data Path (Design-Only)

## Current phase behavior
- Config schema supports `data_source: cloud|local`.
- Runtime fails fast for `local` with a clear `NotImplementedError`.

## Expected local data contract
- `runtime.local_data_dir` must point to LEAN data root.
- FX minute files expected under LEAN forex layout for each pair.
- Canonical pair naming is `EURUSD` in config and artifacts.

## Deferred implementation checklist
1. Implement local path resolver for LEAN FX minute datasets.
2. Add preflight data availability checks per configured symbol/date range.
3. Add local backtest runner wiring (`lean backtest --data-folder ...`).
4. Add integration tests with fixture mini datasets.
5. Add artifact parity checks vs cloud outputs.
