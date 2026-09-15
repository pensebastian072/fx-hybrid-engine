#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "skills" / "public"
SKILL_NAME_RE = re.compile(r"^[a-z0-9-]+$")
REQUIRED_FRONTMATTER_KEYS = {"name", "description"}
REQUIRED_INTERFACE_KEYS = {"display_name", "short_description", "default_prompt"}


def parse_frontmatter(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} is missing YAML frontmatter")

    try:
        end_index = next(idx for idx, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError(f"{path} has unclosed YAML frontmatter") from exc

    raw = "\n".join(lines[1:end_index])
    try:
        payload = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} has invalid YAML frontmatter: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} frontmatter must be a mapping")
    return payload


def validate_skill_dir(path: Path) -> list[str]:
    errors: list[str] = []

    if not SKILL_NAME_RE.fullmatch(path.name):
        errors.append(f"{path.name}: skill directory names must match {SKILL_NAME_RE.pattern}")

    skill_path = path / "SKILL.md"
    if not skill_path.exists():
        errors.append(f"{path.name}: missing SKILL.md")
    else:
        try:
            frontmatter = parse_frontmatter(skill_path)
            missing = REQUIRED_FRONTMATTER_KEYS - set(frontmatter)
            if missing:
                errors.append(f"{path.name}: missing frontmatter keys {sorted(missing)}")
            else:
                if frontmatter["name"] != path.name:
                    errors.append(f"{path.name}: frontmatter name must match directory name")
                description = str(frontmatter["description"]).strip()
                if not description or "[TODO" in description:
                    errors.append(f"{path.name}: description must be populated")
        except OSError as exc:
            errors.append(f"{path.name}: failed to read SKILL.md ({exc})")
        except ValueError as exc:
            errors.append(str(exc))

        try:
            raw_skill = skill_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path.name}: failed to read SKILL.md ({exc})")
        else:
            if "[TODO" in raw_skill:
                errors.append(f"{path.name}: SKILL.md still contains TODO placeholders")

    readme_path = path / "README.md"
    if not readme_path.exists():
        errors.append(f"{path.name}: missing README.md")
    else:
        try:
            raw_readme = readme_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path.name}: failed to read README.md ({exc})")
        else:
            if not raw_readme.strip():
                errors.append(f"{path.name}: README.md must not be empty")
            if "[TODO" in raw_readme:
                errors.append(f"{path.name}: README.md still contains TODO placeholders")

    openai_path = path / "agents" / "openai.yaml"
    if not openai_path.exists():
        errors.append(f"{path.name}: missing agents/openai.yaml")
    else:
        try:
            payload = yaml.safe_load(openai_path.read_text(encoding="utf-8")) or {}
        except OSError as exc:
            errors.append(f"{path.name}: failed to read agents/openai.yaml ({exc})")
        except yaml.YAMLError as exc:
            errors.append(f"{path.name}: agents/openai.yaml has invalid YAML ({exc})")
        else:
            interface = payload.get("interface")
            if not isinstance(interface, dict):
                errors.append(f"{path.name}: openai.yaml must contain an interface mapping")
            else:
                missing = REQUIRED_INTERFACE_KEYS - set(interface)
                if missing:
                    errors.append(f"{path.name}: missing openai interface keys {sorted(missing)}")
                for key in REQUIRED_INTERFACE_KEYS & set(interface):
                    value = str(interface[key]).strip()
                    if not value or "[TODO" in value:
                        errors.append(f"{path.name}: interface.{key} must be populated")

    return errors


def validate_skill_tree(root: Path = SKILLS_ROOT) -> dict[str, list[str]]:
    if not root.exists():
        return {str(root): [f"{root} does not exist"]}

    results: dict[str, list[str]] = {}
    for path in sorted(child for child in root.iterdir() if child.is_dir()):
        errors = validate_skill_dir(path)
        if errors:
            results[path.name] = errors
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=SKILLS_ROOT, help="Skill root to validate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        issues = validate_skill_tree(args.root)
    except OSError as exc:
        print(f"Skill validation failed while accessing {args.root}: {exc}", file=sys.stderr)
        return 1
    if issues:
        for skill_name, errors in issues.items():
            print(f"{skill_name}:")
            for error in errors:
                print(f"  - {error}")
        return 1

    print(f"Validated repo skills under {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
