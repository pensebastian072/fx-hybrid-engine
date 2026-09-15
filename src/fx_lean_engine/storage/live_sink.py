"""Append-only persistence sink for paper/live runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


class LiveArtifactSink:
    """Writes append-only parquet/jsonl shards partitioned by day and run id."""

    def __init__(self, output_root: str | Path, run_id: str):
        self.output_root = Path(output_root)
        self.run_id = str(run_id)
        self.output_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        text = str(value or "").strip()
        if not text:
            return datetime.now(tz=UTC)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except Exception:
            return datetime.now(tz=UTC)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    def _run_dir_for_timestamp(self, timestamp: datetime) -> Path:
        day = timestamp.astimezone(UTC).date().isoformat()
        run_dir = self.output_root / day / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def append_parquet_rows(self, artifact_name: str, rows: list[dict[str, Any]]) -> None:
        """Append rows to parquet artifact grouped by event date."""
        if not rows:
            return

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            ts = self._parse_timestamp(row.get("timestamp"))
            key = ts.astimezone(UTC).date().isoformat()
            grouped.setdefault(key, []).append(row)

        for day, day_rows in grouped.items():
            run_dir = self.output_root / day / self.run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            file_path = run_dir / f"{artifact_name}.parquet"
            new_frame = pd.DataFrame(day_rows)
            if file_path.exists():
                existing = pd.read_parquet(file_path)
                merged = pd.concat([existing, new_frame], ignore_index=True)
            else:
                merged = new_frame
            merged.to_parquet(file_path, index=False)

    def append_jsonl_rows(self, artifact_name: str, rows: list[dict[str, Any]]) -> None:
        """Append rows to JSONL artifact grouped by event date."""
        if not rows:
            return

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            ts = self._parse_timestamp(row.get("timestamp"))
            key = ts.astimezone(UTC).date().isoformat()
            grouped.setdefault(key, []).append(row)

        for day, day_rows in grouped.items():
            run_dir = self.output_root / day / self.run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            file_path = run_dir / f"{artifact_name}.jsonl"
            with file_path.open("a", encoding="utf-8") as handle:
                for row in day_rows:
                    handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    def write_run_metadata(
        self,
        timestamp: datetime,
        run_manifest: dict[str, Any],
        config_snapshot: dict[str, Any],
    ) -> None:
        """Write manifest/snapshot in the partition for the supplied timestamp."""
        run_dir = self._run_dir_for_timestamp(timestamp)
        (run_dir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")
        (run_dir / "config_snapshot.yaml").write_text(yaml.safe_dump(config_snapshot, sort_keys=False), encoding="utf-8")
