"""Operational run summary export for Phase 6/7 promotion checks."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return rows


def _reconciliation_mode(event: dict[str, object]) -> str:
    mode = str(event.get("reconciliation_mode", "") or "")
    if mode:
        return mode
    event_name = str(event.get("event", "") or "")
    if event_name == "paper_reconciliation_skipped":
        return "skipped"
    if event_name == "paper_reconciliation_snapshot":
        return "broker_validated"
    return "unspecified"


def generate_ops_summary(
    run_dir: str | Path,
    *,
    write: bool = True,
) -> tuple[dict[str, object], Path]:
    """Aggregate compact ops telemetry for audit and promotion decisions."""
    root = Path(run_dir)
    equity = _read_parquet(root / "equity_curve.parquet")
    targets = _read_parquet(root / "targets.parquet")
    risk_events = _read_parquet(root / "risk_events.parquet")
    signals = _read_parquet(root / "signals.parquet")
    broker_events = _read_jsonl(root / "broker_events.jsonl")
    recon_events = _read_jsonl(root / "reconciliation_events.jsonl")

    reconciliation_mode_counts: dict[str, int] = {}
    for event in recon_events:
        mode = _reconciliation_mode(event)
        reconciliation_mode_counts[mode] = reconciliation_mode_counts.get(mode, 0) + 1

    total_pnl = 0.0
    max_drawdown = 0.0
    if not equity.empty and "equity" in equity.columns:
        eq = equity["equity"].astype(float)
        total_pnl = float(eq.iloc[-1] - eq.iloc[0]) if len(eq) > 1 else 0.0
        peak = eq.cummax()
        dd = ((peak - eq) / peak.replace(0.0, pd.NA)).fillna(0.0)
        max_drawdown = float(dd.max()) if not dd.empty else 0.0

    exposure = 0.0
    max_exposure = 0.0
    if not targets.empty and "target_weight" in targets.columns:
        abs_w = targets["target_weight"].astype(float).abs()
        exposure = float(abs_w.mean()) if not abs_w.empty else 0.0
        max_exposure = float(abs_w.max()) if not abs_w.empty else 0.0

    rejects = sum(1 for ev in broker_events if "reject" in str(ev.get("event", "")).lower())
    stale_events = int((risk_events["reason"].astype(str).str.contains("stale", case=False)).sum()) if ("reason" in risk_events.columns and not risk_events.empty) else 0
    close_only_events = int((risk_events["reason"].astype(str).str.contains("close_only", case=False)).sum()) if ("reason" in risk_events.columns and not risk_events.empty) else 0
    reconcile_failures = sum(
        1
        for ev in recon_events
        if _reconciliation_mode(ev) != "skipped"
        and bool(ev.get("pause_entries"))
        and not bool(ev.get("resolved", False))
    )

    regime_mix: dict[str, float] = {}
    if not signals.empty and "regime_label" in signals.columns:
        counts = signals["regime_label"].astype(str).value_counts(normalize=True)
        regime_mix = {str(k): float(v) for k, v in counts.items()}

    summary: dict[str, object] = {
        "run_dir": str(root),
        "pnl_total": total_pnl,
        "max_drawdown": max_drawdown,
        "mean_abs_exposure": exposure,
        "max_abs_exposure": max_exposure,
        "reject_count": int(rejects),
        "stale_event_count": int(stale_events),
        "close_only_event_count": int(close_only_events),
        "reconciliation_failure_count": int(reconcile_failures),
        "reconciliation_event_count": int(len(recon_events)),
        "reconciliation_mode_counts": reconciliation_mode_counts,
        "regime_mix": regime_mix,
    }
    out_path = root / "ops_summary.json"
    if write:
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary, out_path

