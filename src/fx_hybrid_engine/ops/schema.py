"""Operational artifact schema and append-audit validation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED_STREAMS: dict[str, str] = {
    "bars": "bars.parquet",
    "features": "features.parquet",
    "signals": "signals.parquet",
    "targets": "targets.parquet",
    "orders": "orders.parquet",
    "fills": "fills.parquet",
    "equity_curve": "equity_curve.parquet",
    "risk_events": "risk_events.parquet",
    "broker_events": "broker_events.jsonl",
    "reconciliation_events": "reconciliation_events.jsonl",
}

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "bars": ["timestamp", "run_id", "symbol"],
    "features": ["timestamp", "run_id", "symbol"],
    "signals": ["timestamp", "run_id", "symbol"],
    "targets": ["timestamp", "run_id", "symbol"],
    "orders": ["timestamp", "run_id", "symbol"],
    "fills": ["timestamp", "run_id", "symbol"],
    "equity_curve": ["timestamp", "run_id"],
    "risk_events": ["timestamp", "run_id", "reason"],
}


@dataclass(slots=True)
class OpsIssue:
    level: str
    path: Path
    message: str


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _validate_required_files(run_dir: Path) -> list[OpsIssue]:
    issues: list[OpsIssue] = []
    for stream, rel in REQUIRED_STREAMS.items():
        path = run_dir / rel
        if not path.exists():
            issues.append(OpsIssue("error", path, f"Missing required stream: {stream}"))
    for rel in ("run_manifest.json", "config_snapshot.yaml"):
        path = run_dir / rel
        if not path.exists():
            issues.append(OpsIssue("error", path, f"Missing required metadata file: {rel}"))
    return issues


def _validate_parquet_columns(run_dir: Path, *, require_run_id_columns: bool) -> list[OpsIssue]:
    issues: list[OpsIssue] = []
    for stream, required_cols in REQUIRED_COLUMNS.items():
        path = run_dir / REQUIRED_STREAMS[stream]
        if not path.exists():
            continue
        try:
            df = pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001
            issues.append(OpsIssue("error", path, f"Unable to read parquet: {exc}"))
            continue
        expected = [c for c in required_cols if require_run_id_columns or c != "run_id"]
        missing = [c for c in expected if c not in df.columns]
        if missing:
            issues.append(OpsIssue("error", path, f"Missing columns: {missing}"))
            continue
        if "timestamp" in expected:
            parsed = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            if parsed.isna().any():
                issues.append(OpsIssue("error", path, "Invalid timestamp values present"))
    return issues


def _validate_append_audit(run_dir: Path) -> list[OpsIssue]:
    issues: list[OpsIssue] = []
    audit_path = run_dir / "write_audit.jsonl"
    if not audit_path.exists():
        issues.append(OpsIssue("error", audit_path, "Missing append audit log: write_audit.jsonl"))
        return issues

    rows = _load_jsonl(audit_path)
    by_stream: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        stream = str(row.get("stream", ""))
        by_stream.setdefault(stream, []).append(row)

    for stream, _rel in REQUIRED_STREAMS.items():
        if stream == "broker_events":
            # broker_events are jsonl; still must have audit.
            pass
        entries = by_stream.get(stream, [])
        if not entries:
            issues.append(OpsIssue("error", audit_path, f"No append audit entries for stream: {stream}"))
            continue
        entries = sorted(entries, key=lambda x: int(x.get("append_id", 0)))
        prev_post: int | None = None
        prev_append_id = 0
        for entry in entries:
            append_id = int(entry.get("append_id", 0))
            pre_rows = int(entry.get("pre_rows", -1))
            post_rows = int(entry.get("post_rows", -1))
            rows_added = int(entry.get("rows_added", -1))
            if append_id <= prev_append_id:
                issues.append(OpsIssue("error", audit_path, f"Non-increasing append_id for stream {stream}"))
            prev_append_id = append_id
            if pre_rows < 0 or post_rows < 0 or rows_added < 0:
                issues.append(OpsIssue("error", audit_path, f"Negative audit row counts for stream {stream}"))
            if post_rows < pre_rows:
                issues.append(OpsIssue("error", audit_path, f"post_rows < pre_rows for stream {stream}"))
            if rows_added != (post_rows - pre_rows):
                issues.append(
                    OpsIssue(
                        "error",
                        audit_path,
                        f"rows_added mismatch for stream {stream}: rows_added={rows_added}, delta={post_rows - pre_rows}",
                    )
                )
            if prev_post is not None and pre_rows != prev_post:
                issues.append(OpsIssue("error", audit_path, f"Non-monotonic pre_rows chain for stream {stream}"))
            prev_post = post_rows
    return issues


def _validate_jsonl_required_fields(run_dir: Path) -> list[OpsIssue]:
    issues: list[OpsIssue] = []
    recon_path = run_dir / REQUIRED_STREAMS["reconciliation_events"]
    if recon_path.exists():
        for idx, row in enumerate(_load_jsonl(recon_path)):
            missing = [k for k in ("timestamp", "run_id", "reason") if k not in row]
            if missing:
                issues.append(
                    OpsIssue(
                        "error",
                        recon_path,
                        f"reconciliation_events row {idx} missing required fields: {missing}",
                    )
                )
    return issues


def validate_ops_run_dir(
    run_dir: str | Path,
    *,
    require_run_id_columns: bool = True,
    strict_append_audit: bool = True,
) -> tuple[bool, list[OpsIssue]]:
    root = Path(run_dir)
    issues = _validate_required_files(root)
    issues.extend(_validate_parquet_columns(root, require_run_id_columns=require_run_id_columns))
    issues.extend(_validate_jsonl_required_fields(root))
    if strict_append_audit:
        issues.extend(_validate_append_audit(root))
    ok = not any(issue.level == "error" for issue in issues)
    return ok, issues


def render_ops_issues(issues: list[OpsIssue]) -> str:
    return "\n".join(f"[{issue.level.upper()}] {issue.path}: {issue.message}" for issue in issues)
