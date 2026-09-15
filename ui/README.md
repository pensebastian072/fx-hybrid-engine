# FX Hybrid Engine UI

This directory contains the Next.js dashboard for viewing run artifacts, paper-session outputs, and backend-derived status surfaces for `fx-hybrid-engine`.

## Read Order

1. `../AGENTS.md`
2. `../docs/DEVELOPER.md`
3. `AGENTS.md`
4. `docs/README.md`

## What Lives Here

- `src/` — dashboard routes, API routes, shared UI components, and artifact-loading logic
- `docs/` — secondary UI docs such as Clerk setup, navigation/RBAC notes, and theming guidance
- `public/` — static assets used by the dashboard
- `__CLEANUP__/` — upstream starter cleanup helpers; secondary context only
- `package.json` — UI scripts and dependencies (note: some upstream starter branding still appears here)

## Current Source Of Truth

Use these files first when changing the dashboard:

- `src/lib/server-artifacts.ts`
- `src/lib/fx-types.ts`
- `src/app/api/state/route.ts`
- `src/app/api/run/route.ts`
- `src/config/nav-config.ts`
- `src/app/dashboard/*`

Do not infer trading truth from the UI alone. Backend artifacts, contracts, and repo-level instructions remain authoritative.

## Common Commands

From `ui/`:

- `npm install`
- `npm run dev`
- `npm run lint:strict`
- `npm run build`

## Workflow Notes

- Keep this README, `AGENTS.md`, and `docs/README.md` aligned when the folder layout or workflow guidance changes.
- When artifact semantics change, update the UI types and API routes in the same change.
- The dashboard must stay truthful about local paper vs broker-native behavior.
- Treat `ui/package.json` branding and any leftover starter-template docs as secondary to the repo-specific guidance above.
