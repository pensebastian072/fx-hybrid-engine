# AGENTS.md - fx-hybrid-engine UI scope

Read the repo root `AGENTS.md` first, then `docs/DEVELOPER.md`, then `ui/README.md`. This file only covers repo-specific UI truth for the dashboard under `ui/`.

## What this UI actually is

- The `ui/` app is the FX Hybrid Engine dashboard built on Next.js 16, TypeScript, and Tailwind.
- The dashboard reads repo artifacts from `artifacts/latest_run/` and `artifacts/mock/`; it is not the source of trading truth by itself.
- Some upstream starter-template branding still exists in `ui/package.json` and secondary example surfaces. Treat the repo docs and the active dashboard files below as authoritative instead.

## UI source of truth

When changing the dashboard, prefer these files:

- `ui/src/lib/server-artifacts.ts`
- `ui/src/lib/fx-types.ts`
- `ui/src/app/api/state/route.ts`
- `ui/src/app/api/run/route.ts`
- `ui/src/config/nav-config.ts`
- `ui/src/app/dashboard/algo/page.tsx`
- `ui/src/app/dashboard/paper/page.tsx`
- `ui/src/app/dashboard/*`

Treat `ui/docs/`, starter-template branding in `ui/package.json`, and unrelated example routes as secondary context unless the active dashboard still references them.

## Required UI invariants

- Preserve artifact provenance. The UI must distinguish `latest_run`, `mock`, and mixed data correctly.
- Do not imply broker-native paper/live trading if the backend only emits local-paper artifacts.
- If backend artifact names, manifest fields, or provenance semantics change, update the TypeScript types and API routes in the same change.
- Keep the dashboard aligned with backend truth from `src/fx_hybrid_engine/`, `docs/CONTRACTS.md`, and `docs/OPERATIONS.md`.
- Keep `ui/README.md` and `ui/docs/README.md` aligned when the folder layout or contributor workflow changes.

## Validation

From `ui/`, use:

- `npm run lint:strict`
- `npm run build`

If the change also affects repo-wide agent or workflow docs, run:

- `python ..\\scripts\\sync_agent_docs.py --write` when root `AGENTS.md` changes
- `python ..\\scripts\\validate_repo_skills.py`
- `python -m pytest ..\\tests\\unit\\test_agent_system.py -q`

## Secondary UI docs

Use `ui/docs/README.md` as the index for optional UI-specific docs such as Clerk setup, navigation/RBAC notes, and theming guidance. Keep this `AGENTS.md` focused on repo-specific UI truth rather than generic framework or vendor docs.
