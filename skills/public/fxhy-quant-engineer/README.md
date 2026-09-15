# fxhy-quant-engineer

Use this role for current backend, quant, config, and evaluation work in `src/fx_hybrid_engine/`.

## Read First

1. [`../../../AGENTS.md`](../../../AGENTS.md)
2. [`../../../src/fx_hybrid_engine/AGENTS.md`](../../../src/fx_hybrid_engine/AGENTS.md)
3. [`../../../src/fx_hybrid_engine/README.md`](../../../src/fx_hybrid_engine/README.md)
4. [`SKILL.md`](SKILL.md)

## What This Folder Owns

- `SKILL.md` — backend execution rules and handoff boundaries
- `agents/openai.yaml` — CLI-facing role descriptor

## Use This Role For

- data providers and feature logic
- engines, regime logic, and risk behavior
- config-backed backend behavior
- reporting, evaluation, and artifact-producing backend changes

## Validation Bias

- Start with targeted unit tests.
- Broaden to smoke or contract validation when artifacts or the main loop change.
