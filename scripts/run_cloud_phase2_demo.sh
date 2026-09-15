#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_ID="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_DIR="${PROJECT_ROOT}/outputs/backtests/cloud_phase2_demo_${RUN_ID}"

if ! command -v lean >/dev/null 2>&1; then
  echo "LEAN CLI not found. Install with: python -m pip install lean"
  exit 1
fi

if [[ -n "${QC_USER_ID:-}" && -n "${QC_API_TOKEN:-}" ]]; then
  lean login --user-id "${QC_USER_ID}" --api-token "${QC_API_TOKEN}"
fi

: "${LEAN_PROJECT_ID:?Set LEAN_PROJECT_ID to the QuantConnect project id}"

mkdir -p "${OUT_DIR}"

lean cloud backtest "${LEAN_PROJECT_ID}" \
  --name "fxle_phase2_demo_${RUN_ID}" \
  --parameter backtest_config backtest_phase2_demo.yaml \
  --parameter phase2_pairs_gating_enabled true \
  --push \
  --open \
  > "${OUT_DIR}/lean_cloud_phase2_demo.log"

if [[ -f "${OUT_DIR}/metrics.json" || -f "${OUT_DIR}/summary.json" ]]; then
  PYTHONPATH="${PROJECT_ROOT}/src" python3 "${SCRIPT_DIR}/validate_backtest_artifacts.py" --run-dir "${OUT_DIR}" --require-phase2
else
  echo "Cloud run submitted. No local artifact bundle detected at ${OUT_DIR}; skipping contract validation."
fi
