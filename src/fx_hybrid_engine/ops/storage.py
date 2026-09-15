"""Append-only storage contract for Phase 6/7 operational telemetry."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

AUDIT_FILENAME = "write_audit.jsonl"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_manifest_run_id(run_dir: Path) -> str | None:
    manifest = run_dir / "run_manifest.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return data.get("run_id") or data.get("wf_run_id")


def _resolve_run_id(run_dir: Path, frame: pd.DataFrame | None, run_id: str | None) -> str:
    if run_id:
        return str(run_id)
    if frame is not None and "run_id" in frame.columns and not frame.empty:
        candidate = frame["run_id"].dropna()
        if not candidate.empty:
            return str(candidate.iloc[0])
    from_manifest = _load_manifest_run_id(run_dir)
    if from_manifest:
        return str(from_manifest)
    return "unknown_run"


def _rows_in_parquet(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return int(len(pd.read_parquet(path)))
    except Exception:  # noqa: BLE001
        return 0


def _rows_in_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _next_append_id(run_dir: Path, stream: str) -> int:
    audit = run_dir / AUDIT_FILENAME
    if not audit.exists():
        return 1
    last = 0
    for line in audit.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("stream", "")) == stream:
            last = max(last, int(row.get("append_id", 0)))
    return last + 1


def _append_audit(
    run_dir: Path,
    *,
    stream: str,
    rows_added: int,
    pre_rows: int,
    post_rows: int,
) -> Path:
    path = run_dir / AUDIT_FILENAME
    append_id = _next_append_id(run_dir, stream)
    payload = {
        "timestamp": _utc_now_iso(),
        "stream": stream,
        "append_id": append_id,
        "rows_added": int(rows_added),
        "pre_rows": int(pre_rows),
        "post_rows": int(post_rows),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True))
        f.write("\n")
    return path


def _append_parquet(path: Path, frame: pd.DataFrame) -> tuple[Path, int, int]:
    pre_rows = _rows_in_parquet(path)
    if frame.empty:
        if not path.exists():
            frame.to_parquet(path, index=False)
        return path, 0, pre_rows

    if path.exists():
        existing = pd.read_parquet(path)
        cols = list(dict.fromkeys([*existing.columns, *frame.columns]))
        combined = pd.concat(
            [
                existing.reindex(columns=cols),
                frame.reindex(columns=cols),
            ],
            ignore_index=True,
        )
    else:
        combined = frame.reset_index(drop=True)
    combined.to_parquet(path, index=False)
    post_rows = len(combined)
    return path, int(post_rows - pre_rows), post_rows


def _append_stream(
    run_dir: str | Path,
    *,
    stream: str,
    filename: str,
    frame: pd.DataFrame,
    run_id: str | None = None,
) -> Path:
    root = Path(run_dir)
    _ensure_dir(root)
    run_value = _resolve_run_id(root, frame, run_id)
    data = frame.copy()
    if "run_id" not in data.columns:
        data["run_id"] = run_value
    if "timestamp" not in data.columns:
        data["timestamp"] = _utc_now_iso()

    target = root / filename
    pre_rows = _rows_in_parquet(target)
    _, rows_added, post_rows = _append_parquet(target, data)
    _append_audit(root, stream=stream, rows_added=rows_added, pre_rows=pre_rows, post_rows=post_rows)
    return target


def append_bars(run_dir: str | Path, frame: pd.DataFrame, *, run_id: str | None = None) -> Path:
    return _append_stream(run_dir, stream="bars", filename="bars.parquet", frame=frame, run_id=run_id)


def append_features(run_dir: str | Path, frame: pd.DataFrame, *, run_id: str | None = None) -> Path:
    return _append_stream(run_dir, stream="features", filename="features.parquet", frame=frame, run_id=run_id)


def append_signals(run_dir: str | Path, frame: pd.DataFrame, *, run_id: str | None = None) -> Path:
    return _append_stream(run_dir, stream="signals", filename="signals.parquet", frame=frame, run_id=run_id)


def append_targets(run_dir: str | Path, frame: pd.DataFrame, *, run_id: str | None = None) -> Path:
    return _append_stream(run_dir, stream="targets", filename="targets.parquet", frame=frame, run_id=run_id)


def append_orders(run_dir: str | Path, frame: pd.DataFrame, *, run_id: str | None = None) -> Path:
    return _append_stream(run_dir, stream="orders", filename="orders.parquet", frame=frame, run_id=run_id)


def append_fills(run_dir: str | Path, frame: pd.DataFrame, *, run_id: str | None = None) -> Path:
    return _append_stream(run_dir, stream="fills", filename="fills.parquet", frame=frame, run_id=run_id)


def append_equity_curve(run_dir: str | Path, frame: pd.DataFrame, *, run_id: str | None = None) -> Path:
    return _append_stream(
        run_dir,
        stream="equity_curve",
        filename="equity_curve.parquet",
        frame=frame,
        run_id=run_id,
    )


def append_risk_events(run_dir: str | Path, frame: pd.DataFrame, *, run_id: str | None = None) -> Path:
    return _append_stream(
        run_dir,
        stream="risk_events",
        filename="risk_events.parquet",
        frame=frame,
        run_id=run_id,
    )


def append_pair_scans(run_dir: str | Path, frame: pd.DataFrame, *, run_id: str | None = None) -> Path:
    return _append_stream(
        run_dir,
        stream="pair_scans",
        filename="pair_scans.parquet",
        frame=frame,
        run_id=run_id,
    )


def append_pair_state_events(
    run_dir: str | Path,
    frame: pd.DataFrame,
    *,
    run_id: str | None = None,
) -> Path:
    return _append_stream(
        run_dir,
        stream="pair_state_events",
        filename="pair_state_events.parquet",
        frame=frame,
        run_id=run_id,
    )


def append_indicator_snapshots(
    run_dir: str | Path,
    frame: pd.DataFrame,
    *,
    run_id: str | None = None,
) -> Path:
    return _append_stream(
        run_dir,
        stream="indicator_snapshots",
        filename="indicator_snapshots.parquet",
        frame=frame,
        run_id=run_id,
    )


def append_broker_events(
    run_dir: str | Path,
    events: list[dict[str, Any]],
    *,
    run_id: str | None = None,
) -> Path:
    root = Path(run_dir)
    _ensure_dir(root)
    run_value = _resolve_run_id(root, None, run_id)
    path = root / "broker_events.jsonl"
    pre_rows = _rows_in_jsonl(path)

    if not events:
        path.touch(exist_ok=True)
        _append_audit(root, stream="broker_events", rows_added=0, pre_rows=pre_rows, post_rows=pre_rows)
        return path

    with open(path, "a", encoding="utf-8") as f:
        for event in events:
            payload = dict(event)
            payload.setdefault("run_id", run_value)
            payload.setdefault("timestamp", _utc_now_iso())
            f.write(json.dumps(payload, sort_keys=True, default=str))
            f.write("\n")
    post_rows = _rows_in_jsonl(path)
    _append_audit(
        root,
        stream="broker_events",
        rows_added=post_rows - pre_rows,
        pre_rows=pre_rows,
        post_rows=post_rows,
    )
    return path


def append_broker_context(
    run_dir: str | Path,
    events: list[dict[str, Any]],
    *,
    run_id: str | None = None,
) -> Path:
    root = Path(run_dir)
    _ensure_dir(root)
    run_value = _resolve_run_id(root, None, run_id)
    path = root / "broker_context.jsonl"
    pre_rows = _rows_in_jsonl(path)

    if not events:
        path.touch(exist_ok=True)
        _append_audit(root, stream="broker_context", rows_added=0, pre_rows=pre_rows, post_rows=pre_rows)
        return path

    with open(path, "a", encoding="utf-8") as f:
        for event in events:
            payload = dict(event)
            payload.setdefault("run_id", run_value)
            payload.setdefault("timestamp", _utc_now_iso())
            f.write(json.dumps(payload, sort_keys=True, default=str))
            f.write("\n")
    post_rows = _rows_in_jsonl(path)
    _append_audit(
        root,
        stream="broker_context",
        rows_added=post_rows - pre_rows,
        pre_rows=pre_rows,
        post_rows=post_rows,
    )
    return path


def append_reconciliation_events(
    run_dir: str | Path,
    events: list[dict[str, Any]],
    *,
    run_id: str | None = None,
) -> Path:
    """Append reconciliation events as JSONL with append-audit tracking."""
    root = Path(run_dir)
    _ensure_dir(root)
    run_value = _resolve_run_id(root, None, run_id)
    path = root / "reconciliation_events.jsonl"
    pre_rows = _rows_in_jsonl(path)

    if not events:
        path.touch(exist_ok=True)
        _append_audit(root, stream="reconciliation_events", rows_added=0, pre_rows=pre_rows, post_rows=pre_rows)
        return path

    with open(path, "a", encoding="utf-8") as f:
        for event in events:
            payload = dict(event)
            payload.setdefault("run_id", run_value)
            payload.setdefault("timestamp", _utc_now_iso())
            f.write(json.dumps(payload, sort_keys=True, default=str))
            f.write("\n")
    post_rows = _rows_in_jsonl(path)
    _append_audit(
        root,
        stream="reconciliation_events",
        rows_added=post_rows - pre_rows,
        pre_rows=pre_rows,
        post_rows=post_rows,
    )
    return path


def initialize_run_metadata(
    run_dir: str | Path,
    run_manifest: dict[str, Any],
    config_snapshot: dict[str, Any],
) -> tuple[Path, Path]:
    """Write run metadata artifacts once; raises if they already exist."""
    root = Path(run_dir)
    _ensure_dir(root)
    manifest_path = root / "run_manifest.json"
    snapshot_path = root / "config_snapshot.yaml"
    if manifest_path.exists():
        raise FileExistsError(f"run_manifest already exists: {manifest_path}")
    if snapshot_path.exists():
        raise FileExistsError(f"config_snapshot already exists: {snapshot_path}")
    manifest_payload = dict(run_manifest)
    manifest_payload.setdefault("created_at_utc", _utc_now_iso())
    manifest_payload.setdefault("run_id", manifest_payload.get("wf_run_id", "unknown_run"))
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8")
    snapshot_path.write_text(yaml.safe_dump(config_snapshot, sort_keys=False), encoding="utf-8")
    return manifest_path, snapshot_path
