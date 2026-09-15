#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = REPO_ROOT / "AGENTS.md"
COPILOT_PATH = REPO_ROOT / ".github" / "copilot-instructions.md"
GENERATED_HEADER = """# Copilot Instructions — fx-hybrid-engine

This file is generated from `AGENTS.md` by `scripts/sync_agent_docs.py`.
Do not edit directly. Edit `AGENTS.md`, then run `make ai-sync`.

---
"""


def strip_root_title(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).rstrip() + "\n"


def render_copilot_instructions(agents_text: str) -> str:
    return GENERATED_HEADER + "\n" + strip_root_title(agents_text)


def build_expected_output() -> str:
    agents_text = AGENTS_PATH.read_text(encoding="utf-8")
    return render_copilot_instructions(agents_text)


def write_output() -> None:
    COPILOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    COPILOT_PATH.write_text(build_expected_output(), encoding="utf-8")


def check_output() -> bool:
    expected = build_expected_output()
    actual = COPILOT_PATH.read_text(encoding="utf-8") if COPILOT_PATH.exists() else ""
    if actual == expected:
        return True

    diff = difflib.unified_diff(
        actual.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile=str(COPILOT_PATH),
        tofile="expected generated output",
    )
    sys.stdout.writelines(diff)
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Write generated output to .github")
    mode.add_argument("--check", action="store_true", help="Fail if .github output is stale")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.write:
            write_output()
            print(f"Wrote {COPILOT_PATH}")
            return 0
        if check_output():
            print(f"{COPILOT_PATH} is up to date")
            return 0
        return 1
    except FileNotFoundError as exc:
        missing_path = Path(exc.filename).resolve() if exc.filename else exc
        print(f"Copilot instruction sync failed because a required file is missing: {missing_path}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Copilot instruction sync failed while accessing repo files: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
