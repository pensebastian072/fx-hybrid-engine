"""Parity verification utilities for cache and fallback walk-forward paths."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

METRIC_COLUMNS = ("total_return", "sharpe", "max_drawdown", "trades")
KEY_COLUMNS = ("split_idx", "mode")
PROFILE_EPSILON = {
    "local_smoke": 1e-6,
    "external": 1e-3,
    "openbb": 1e-3,
}


def _load_metrics(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "metrics_by_split.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing metrics file: {path}")
    df = pd.read_csv(path)
    required = [*KEY_COLUMNS, *METRIC_COLUMNS]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required metrics columns in {path}: {missing}")
    return df[required].copy()


def _pairs(df: pd.DataFrame) -> set[tuple[int, str]]:
    return {(int(row["split_idx"]), str(row["mode"])) for _, row in df.iterrows()}


def verify_parity(
    run_a: str | Path,
    run_b: str | Path,
    profile: str = "local_smoke",
    epsilon: float | None = None,
    output_path: str | Path | None = None,
) -> dict[str, object]:
    """Compare walk-forward metrics across two run directories."""
    path_a = Path(run_a)
    path_b = Path(run_b)
    eps = float(epsilon if epsilon is not None else PROFILE_EPSILON.get(profile, 1e-3))

    a = _load_metrics(path_a)
    b = _load_metrics(path_b)
    pairs_a = _pairs(a)
    pairs_b = _pairs(b)
    missing_in_a = sorted(pairs_b - pairs_a)
    missing_in_b = sorted(pairs_a - pairs_b)

    merged = a.merge(b, on=list(KEY_COLUMNS), suffixes=("_a", "_b"), how="inner")
    deltas: list[dict[str, object]] = []
    fail_count = 0
    for _, row in merged.iterrows():
        split_idx = int(row["split_idx"])
        mode = str(row["mode"])
        for metric in METRIC_COLUMNS:
            va = float(row[f"{metric}_a"])
            vb = float(row[f"{metric}_b"])
            delta = abs(va - vb)
            ok = delta <= eps
            if not ok:
                fail_count += 1
            deltas.append(
                {
                    "split_idx": split_idx,
                    "mode": mode,
                    "metric": metric,
                    "value_a": va,
                    "value_b": vb,
                    "abs_delta": delta,
                    "within_epsilon": ok,
                }
            )

    status = (fail_count == 0) and (len(missing_in_a) == 0) and (len(missing_in_b) == 0)
    report: dict[str, object] = {
        "run_a": str(path_a),
        "run_b": str(path_b),
        "profile": profile,
        "epsilon": eps,
        "pass": status,
        "missing_in_a": [{"split_idx": i, "mode": m} for i, m in missing_in_a],
        "missing_in_b": [{"split_idx": i, "mode": m} for i, m in missing_in_b],
        "summary": {
            "matched_pairs": int(len(merged)),
            "checked_metrics": int(len(deltas)),
            "failed_metrics": int(fail_count),
        },
        "deltas": deltas,
    }

    out = Path(output_path) if output_path is not None else (path_a / "parity_report.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["output_path"] = str(out)
    return report

