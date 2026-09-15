"""Promotion gate decisioning based on Phase 5 proof + paper telemetry."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_hybrid_engine.ops.ladder import decide_ladder_action, normalize_stage
from fx_hybrid_engine.ops.ops_summary import generate_ops_summary
from fx_hybrid_engine.utils.config import EngineConfig


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _reconciliation_mode_counts(events: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        mode = _reconciliation_mode(event)
        counts[mode] = counts.get(mode, 0) + 1
    return counts


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


def _within_window(ts: object, cutoff: datetime) -> bool:
    val = pd.to_datetime(ts, utc=True, errors="coerce")
    return bool(not pd.isna(val) and val.to_pydatetime() >= cutoff)


def run_promotion_check(
    *,
    cfg: EngineConfig,
    wf_run_dir: str | Path,
    paper_run_dir: str | Path,
    window_days: int | None = None,
    output_path: str | Path | None = None,
) -> tuple[dict[str, object], Path]:
    """Compute deterministic promotion decision JSON."""
    wf_root = Path(wf_run_dir)
    paper_root = Path(paper_run_dir)
    summary = _read_json(wf_root / "phase5_report_summary.json")
    proof = _read_json(wf_root / "proof_checks.json")
    gates = summary.get("go_no_go", {}) if isinstance(summary.get("go_no_go"), dict) else {}
    final_go = bool(summary.get("final_go", False))

    ops_summary, _ = generate_ops_summary(paper_root, write=True)
    days = int(window_days or cfg.promotion.paper_window_days)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    broker_events = _read_jsonl(paper_root / "broker_events.jsonl")
    recon_events = _read_jsonl(paper_root / "reconciliation_events.jsonl")
    recent_broker = [ev for ev in broker_events if _within_window(ev.get("timestamp"), cutoff)]
    recent_recon = [ev for ev in recon_events if _within_window(ev.get("timestamp"), cutoff)]
    reject_count = sum(1 for ev in recent_broker if "reject" in str(ev.get("event", "")).lower())
    stale_count = sum(1 for ev in recent_broker if "stale" in str(ev.get("event", "")).lower())
    reconcile_mode_counts = _reconciliation_mode_counts(recent_recon)
    reconcile_failures = sum(
        1
        for ev in recent_recon
        if _reconciliation_mode(ev) != "skipped"
        and bool(ev.get("pause_entries"))
        and not bool(ev.get("resolved", False))
    )

    checks = {
        "phase5_final_go": final_go,
        "proof_attribution_gate": bool(proof.get("pass", False)) if cfg.promotion.require_attribution_gate else True,
        "proof_cost_gate": bool(gates.get("costs_do_not_kill_edge", True)) if cfg.promotion.require_cost_gate else True,
        "proof_drawdown_gate": bool(gates.get("worst_split_drawdown_survivable", True)) if cfg.promotion.require_drawdown_gate else True,
        "reject_incidents_ok": reject_count <= int(cfg.promotion.max_rejects_in_window),
        "stale_incidents_ok": stale_count <= int(cfg.promotion.max_stale_events_in_window),
        "reconcile_incidents_ok": reconcile_failures <= int(cfg.promotion.max_reconcile_failures_in_window),
    }
    severe_fail = not (
        checks["proof_attribution_gate"]
        and checks["proof_cost_gate"]
        and checks["proof_drawdown_gate"]
        and checks["reject_incidents_ok"]
        and checks["reconcile_incidents_ok"]
    )
    final_pass = all(bool(v) for v in checks.values())
    current_stage = normalize_stage(cfg.micro_live_ladder.active_stage)
    ladder = decide_ladder_action(current_stage, final_go=final_pass, severe_fail=severe_fail)

    reasons_fail = [k for k, v in checks.items() if not bool(v)]
    decision = {
        "wf_run_dir": str(wf_root),
        "paper_run_dir": str(paper_root),
        "window_days": days,
        "pass": final_pass,
        "checks": checks,
        "failed_reasons": reasons_fail,
        "incident_counts": {
            "reject_count": int(reject_count),
            "stale_count": int(stale_count),
            "reconcile_failures": int(reconcile_failures),
            "reconcile_mode_counts": reconcile_mode_counts,
        },
        "ops_summary": ops_summary,
        "ladder": ladder,
    }
    out = Path(output_path) if output_path else (wf_root / "promotion_decision.json")
    out.write_text(json.dumps(decision, indent=2), encoding="utf-8")
    return decision, out

