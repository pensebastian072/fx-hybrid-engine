"""Phase 6 completion precheck: static artifact + deterministic harness gates."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_hybrid_engine.ops.circuit_breakers import BreakerContext, evaluate_circuit_breakers
from fx_hybrid_engine.ops.execution_policy import apply_close_only_policy
from fx_hybrid_engine.ops.health import HealthPolicy, evaluate_health
from fx_hybrid_engine.ops.ops_summary import generate_ops_summary
from fx_hybrid_engine.ops.reconcile import evaluate_reconciliation
from fx_hybrid_engine.ops.schema import render_ops_issues, validate_ops_run_dir
from fx_hybrid_engine.utils.config import EngineConfig, load_config


@dataclass(slots=True)
class GateResult:
    name: str
    passed: bool
    details: dict[str, object]


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _infer_reconciliation_mode(event: dict[str, object]) -> str:
    mode = str(event.get("reconciliation_mode", "") or "")
    if mode:
        return mode
    event_name = str(event.get("event", "") or "")
    if event_name == "paper_reconciliation_skipped":
        return "skipped"
    if event_name == "paper_reconciliation_snapshot":
        return "broker_validated"
    return ""


def _reconciliation_contract(root: Path, rail: str) -> dict[str, object]:
    def _from_events() -> dict[str, object] | None:
        recon_events = _read_jsonl(root / "reconciliation_events.jsonl")
        if not recon_events:
            return None
        latest = recon_events[-1]
        mode = _infer_reconciliation_mode(latest)
        status = str(latest.get("reconciliation_status", "") or "")
        if not status:
            status = "skipped" if mode == "skipped" else "evaluated" if mode else "missing"
        reason = latest.get("reconciliation_reason") or latest.get("reason")
        explicit = bool(mode) and bool(status) and mode in {"broker_validated", "simulated", "skipped"}
        return {
            "required": True,
            "mode": mode or "missing",
            "status": status,
            "reason": reason,
            "explicit": explicit,
            "source": "reconciliation_events.jsonl",
        }

    safety = _read_json(root / "paper_safety_summary.json")
    if safety:
        mode = str(safety.get("reconciliation_mode", "") or "")
        status = str(safety.get("reconciliation_status", "") or "")
        reason = safety.get("reconciliation_reason")
        explicit = mode in {"broker_validated", "simulated", "skipped"} and bool(status)
        if not explicit:
            inferred = _from_events()
            if inferred is not None and bool(inferred.get("explicit")):
                return inferred
        return {
            "required": True,
            "mode": mode or "missing",
            "status": status or "missing",
            "reason": reason,
            "explicit": explicit,
            "source": "paper_safety_summary.json",
        }

    inferred = _from_events()
    if inferred is not None:
        return inferred

    if rail == "local_paper":
        return {
            "required": True,
            "mode": "missing",
            "status": "missing",
            "reason": "local_paper_requires_explicit_reconciliation_contract",
            "explicit": False,
            "source": "missing",
        }

    return {
        "required": False,
        "mode": "not_applicable",
        "status": "not_applicable",
        "reason": None,
        "explicit": True,
        "source": "not_applicable",
    }


def _health_policy(cfg: EngineConfig) -> HealthPolicy:
    t = cfg.health_monitor.state_machine_thresholds
    return HealthPolicy(
        data_stale_seconds=int(t.get("data_stale_seconds", 300)),
        degraded_rejects=int(t.get("degraded_rejects", 3)),
        broker_down_rejects=int(t.get("broker_down_rejects", 8)),
        max_missing_bars=1,
    )


def _run_harness_gates(cfg: EngineConfig) -> list[GateResult]:
    out: list[GateResult] = []
    now = datetime.now(UTC)

    # stale data -> close_only -> new entries blocked
    stale = evaluate_health(
        now_utc=now,
        last_bar_timestamp_utc=now - timedelta(seconds=3600),
        consecutive_rejects=0,
        policy=_health_policy(cfg),
    )
    policy = apply_close_only_policy(
        current_weights={"EURUSD": 0.0},
        proposed_targets={"EURUSD": 0.15},
        close_only=bool(stale["close_only"]),
    )
    out.append(
        GateResult(
            name="stale_data_close_only_blocks_entries",
            passed=bool(stale["close_only"]) and len(policy.blocked_actions) > 0,
            details={"health": stale, "blocked_actions": policy.blocked_actions},
        )
    )

    # mismatch -> reconcile action (+ optional flatten when persistent)
    recon = evaluate_reconciliation(
        expected_holdings={"EURUSD": 1.0},
        actual_holdings={"EURUSD": 0.3},
        expected_order_ids={"o1"},
        actual_order_ids={"o2"},
        tolerance=cfg.reconciliation.qty_tolerance,
        mismatch_cycles=cfg.reconciliation.persistent_mismatch_cycles,
        persistent_mismatch_cycles=cfg.reconciliation.persistent_mismatch_cycles,
        auto_flatten_on_persistent_mismatch=cfg.reconciliation.auto_flatten_on_persistent_mismatch,
    )
    out.append(
        GateResult(
            name="reconciliation_mismatch_handled",
            passed=recon.pause_entries and recon.attempt_reconcile,
            details={
                "pause_entries": recon.pause_entries,
                "attempt_reconcile": recon.attempt_reconcile,
                "flatten_required": recon.flatten_required,
            },
        )
    )

    # daily loss breaker
    breaker = evaluate_circuit_breakers(
        BreakerContext(
            daily_return=-(cfg.circuit_breakers.daily_loss_limit + 0.01),
            weekly_return=0.0,
            consecutive_losses=0,
            realized_vol_multiple=1.0,
            reject_count=0,
        ),
        cfg.circuit_breakers,
    )
    out.append(
        GateResult(
            name="daily_loss_breaker_triggers",
            passed="daily_loss_limit" in breaker["triggered"] and bool(breaker["pause_entries"]),
            details=breaker,
        )
    )
    return out


def _render_markdown(run_dir: Path, final_pass: bool, gates: list[GateResult], issues_text: str) -> Path:
    lines = [
        "# Phase 6 Precheck",
        "",
        f"Run Directory: `{run_dir}`",
        f"Result: **{'PASS' if final_pass else 'FAIL'}**",
        "",
        "## Gate Results",
    ]
    for gate in gates:
        lines.append(f"- {'PASS' if gate.passed else 'FAIL'}: {gate.name}")
    lines.extend(["", "## Contract Issues", issues_text or "No issues."])
    path = run_dir / "phase6_precheck.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_phase6_precheck(
    run_dir: str | Path,
    *,
    config_path: str | Path = "config/default.yaml",
    docs_path: str | Path = "docs/OPERATIONS.md",
    strict_full: bool = True,
    rail: str = "qc_paper",
    paper_window_days: int | None = None,
) -> tuple[Path, Path, bool]:
    cfg = load_config(config_path)
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)

    ok_contract, issues = validate_ops_run_dir(
        root,
        require_run_id_columns=cfg.ops.require_run_id_columns,
        strict_append_audit=cfg.ops.strict_append_audit,
    )
    gates: list[GateResult] = []

    if strict_full:
        gates.extend(_run_harness_gates(cfg))

    summary_payload, summary_path = generate_ops_summary(root, write=True)
    required_summary_keys = {
        "pnl_total",
        "max_drawdown",
        "mean_abs_exposure",
        "reject_count",
        "stale_event_count",
        "reconciliation_failure_count",
    }
    gates.append(
        GateResult(
            name="ops_summary_present_and_valid",
            passed=summary_path.exists() and required_summary_keys.issubset(set(summary_payload.keys())),
            details={"ops_summary_path": str(summary_path), "keys": sorted(summary_payload.keys())},
        )
    )

    health_enabled = bool(cfg.health_monitor.state_machine_thresholds)
    gates.append(
        GateResult(
            name="health_monitor_enabled",
            passed=health_enabled,
            details={"state_machine_thresholds": cfg.health_monitor.state_machine_thresholds},
        )
    )
    gates.append(
        GateResult(
            name="reconciliation_policy_configured",
            passed=bool(cfg.reconciliation.enabled),
            details={"reconciliation": cfg.reconciliation.__dict__},
        )
    )
    reconciliation_contract = _reconciliation_contract(root, rail)
    gates.append(
        GateResult(
            name="reconciliation_mode_explicit",
            passed=bool(reconciliation_contract["explicit"]),
            details=reconciliation_contract,
        )
    )
    breakers_enabled = (
        cfg.circuit_breakers.daily_loss_limit > 0
        and cfg.circuit_breakers.weekly_loss_limit > 0
        and cfg.circuit_breakers.max_consecutive_losses > 0
    )
    gates.append(
        GateResult(
            name="circuit_breakers_enabled",
            passed=breakers_enabled,
            details={"circuit_breakers": cfg.circuit_breakers.__dict__},
        )
    )

    docs_exists = Path(docs_path).exists()
    gates.append(
        GateResult(
            name="operations_runbook_present",
            passed=docs_exists,
            details={"docs_path": str(Path(docs_path).resolve()), "exists": docs_exists},
        )
    )

    final_pass = ok_contract and all(g.passed for g in gates)
    report = {
        "run_dir": str(root),
        "strict_full": strict_full,
        "rail": rail,
        "paper_window_days": int(paper_window_days or cfg.promotion.paper_window_days),
        "contract_ok": ok_contract,
        "contract_issues": [
            {"level": i.level, "path": str(i.path), "message": i.message}
            for i in issues
        ],
        "gates": [
            {"name": g.name, "passed": g.passed, "details": g.details}
            for g in gates
        ],
        "pass": final_pass,
    }
    json_path = root / "phase6_precheck_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = _render_markdown(root, final_pass, gates, render_ops_issues(issues))
    return json_path, md_path, final_pass
