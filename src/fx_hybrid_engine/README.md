# fx_hybrid_engine Package

This is the current backend implementation surface for `fx-hybrid-engine`.

## Read First

1. [`../../AGENTS.md`](../../AGENTS.md)
2. [`AGENTS.md`](AGENTS.md)
3. [`../../config/README.md`](../../config/README.md)
4. [`../../docs/CONTRACTS.md`](../../docs/CONTRACTS.md)
5. [`../../docs/OPERATIONS.md`](../../docs/OPERATIONS.md)

## Key Areas

- `data/` — provider abstraction and history ingestion
- `features/` — indicators and feature-building logic
- `engines/` — pairs and trend engines
- `regime/` — regime classification and orchestration
- `risk/` — position sizing and safety rules
- `portfolio/` — signal aggregation and portfolio logic
- `brokers/` and `ops/` — paper/live workflow and broker-aware logic
- `evaluation/` and `reporting/` — metrics and report generation
- `lean/` — Lean/QC bridge surfaces
- `utils/` — config and shared support code
- `cli.py` — CLI entry points

## Validation Bias

- Start with targeted unit tests: `python -m pytest tests\unit\<file>.py -q`
- Broaden with repo commands such as `make test`, `make smoke`, `fxhe-phase6-precheck`, or `fxhe-live-precheck` when the scope requires it
