"""Verify that ML4T vendor directories exist and print their current commit SHAs.

Usage:
    python scripts/vendor_check.py

Exit codes:
    0 — both vendor directories found
    1 — one or more vendor directories missing (run scripts/vendor_setup.ps1 to fix)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VENDOR_DIRS = [
    ("vendor/ml4t-jansen", "stefan-jansen/machine-learning-for-trading"),
    ("vendor/ml4t-gatech", "cwu392/Machine-Learning-for-Trading"),
]


def _git_sha(path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "(git error)"
    except Exception:
        return "(git unavailable)"


def main() -> int:
    repo_root = Path(__file__).parent.parent
    missing: list[str] = []
    rows: list[tuple[str, str, str]] = []

    for rel_dir, source in VENDOR_DIRS:
        full_path = repo_root / rel_dir
        if full_path.exists():
            sha = _git_sha(full_path)
            rows.append((rel_dir, sha, "OK"))
        else:
            rows.append((rel_dir, "—", "MISSING"))
            missing.append(rel_dir)

    max_dir = max(len(r[0]) for r in rows)
    print(f"\n{'Directory':<{max_dir}}  {'SHA':<44}  Status")
    print("-" * (max_dir + 50))
    for rel_dir, sha, status in rows:
        print(f"{rel_dir:<{max_dir}}  {sha:<44}  {status}")

    if missing:
        print(f"\n⚠  Missing vendor dirs: {', '.join(missing)}")
        print("   Run: .\\scripts\\vendor_setup.ps1")
        return 1

    print("\n✓  All vendor directories present.")
    print("   Update docs/ML4T_INTEGRATION.md with the SHAs above for pinning.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
