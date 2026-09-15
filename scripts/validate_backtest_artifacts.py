#!/usr/bin/env python3
"""Validate backtest artifact contract for one run directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from fx_lean_engine.backtest.validation import validate_backtest_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FX backtest artifacts")
    parser.add_argument("--run-dir", required=True, help="Path to fx-lean-engine output run directory")
    parser.add_argument("--require-phase2", action="store_true", help="Require Phase 2 artifact set")
    args = parser.parse_args()

    ok, issues = validate_backtest_artifacts(args.run_dir, require_phase2=bool(args.require_phase2))
    if not ok:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1
    print(f"Artifacts valid: {args.run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
