#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_ID="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_DIR="${PROJECT_ROOT}/outputs/backtests/phase1_verification_${RUN_ID}"

PYTHONPATH="${PROJECT_ROOT}/src" python3 -m fx_lean_engine.cli \
  --output-dir "${OUT_DIR}" \
  --config-dir "${PROJECT_ROOT}/configs" \
  --backtest-config "backtest_phase1_verification.yaml"

PYTHONPATH="${PROJECT_ROOT}/src" python3 "${SCRIPT_DIR}/validate_backtest_artifacts.py" --run-dir "${OUT_DIR}"

echo "Phase 1 verification artifacts: ${OUT_DIR}"
