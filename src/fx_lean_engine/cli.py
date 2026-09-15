"""CLI entrypoints for synthetic smoke and artifact validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fx_lean_engine.backtest.synthetic import run_synthetic_backtest
from fx_lean_engine.backtest.validation import validate_backtest_artifacts


def main_synthetic_smoke(argv: list[str] | None = None) -> int:
    """Run deterministic synthetic smoke backtest."""
    parser = argparse.ArgumentParser(description="Run synthetic FX smoke backtest.")
    parser.add_argument("--output-dir", type=str, default="outputs/backtests/synthetic_smoke")
    parser.add_argument("--config-dir", type=str, default="")
    parser.add_argument("--backtest-config", type=str, default="backtest_smoke.yaml")
    parser.add_argument("--require-phase2", action="store_true", help="Require Phase 2 artifact set")
    args = parser.parse_args(argv)

    out_dir = run_synthetic_backtest(
        output_dir=Path(args.output_dir),
        config_dir=Path(args.config_dir) if args.config_dir else None,
        backtest_config_name=args.backtest_config,
    )
    ok, issues = validate_backtest_artifacts(out_dir, require_phase2=bool(args.require_phase2))
    if not ok:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1
    print(f"Synthetic smoke completed and validated: {out_dir}")
    return 0


def main_validate_backtest(argv: list[str] | None = None) -> int:
    """Validate one run directory against artifact contract."""
    parser = argparse.ArgumentParser(description="Validate FX backtest artifacts.")
    parser.add_argument("--run-dir", type=str, required=True)
    parser.add_argument("--require-phase2", action="store_true", help="Require Phase 2 artifact set")
    args = parser.parse_args(argv)

    ok, issues = validate_backtest_artifacts(args.run_dir, require_phase2=bool(args.require_phase2))
    if not ok:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1
    print(f"Artifacts valid: {args.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_synthetic_smoke())


def main_last_update(argv: list[str] | None = None) -> int:
    """Report the last update timestamp from a backtest or live run directory."""
    parser = argparse.ArgumentParser(description="Report the last update timestamp from a run directory.")
    parser.add_argument("--run-dir", type=str, required=True, help="Path to a backtest or live run output directory.")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        print(f"ERROR: metrics.json not found in {run_dir}")
        return 1

    with metrics_path.open(encoding="utf-8") as fh:
        metrics = json.load(fh)

    last_update = metrics.get("last_update_at")
    if last_update is None:
        print("No last_update_at recorded in metrics.")
    else:
        print(f"Last system update: {last_update}")
    return 0
