"""Deterministic run identity and config hashing helpers."""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger("fxhe.utils.identity")


def hash_config(cfg_dict: Mapping[str, Any]) -> str:
    """Return sha256 hash over canonical sorted JSON config payload."""
    blob = json.dumps(cfg_dict, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def make_run_id(now_utc: datetime, config_hash: str) -> str:
    """Build stable run id from UTC timestamp and config hash suffix."""
    ts = now_utc.astimezone(UTC).strftime("%Y%m%d_%H%M%S")
    suffix = config_hash[:8]
    return f"{ts}_{suffix}"


def resolve_git_commit(repo_root: str | Path | None = None) -> str:
    """Resolve git commit hash with warning fallback when metadata is unavailable."""
    cwd = Path(repo_root).resolve() if repo_root else None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
            cwd=str(cwd) if cwd else None,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Unable to resolve git commit metadata; using 'unknown'")
        return "unknown"
    if result.returncode != 0:
        logger.warning("Git metadata not available in this workspace; using 'unknown'")
        return "unknown"
    commit = result.stdout.strip()
    if not commit:
        logger.warning("Empty git commit metadata; using 'unknown'")
        return "unknown"
    return commit
