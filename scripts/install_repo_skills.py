#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "skills" / "public"
MANIFEST_NAME = ".fxhy-repo-skills.json"


def list_repo_skills(source_root: Path = SKILLS_ROOT) -> list[Path]:
    if not source_root.exists():
        raise RuntimeError(f"Skill source root does not exist: {source_root}")
    return sorted(path for path in source_root.iterdir() if path.is_dir())


def resolve_target_root(explicit_target: Path | None = None) -> Path:
    if explicit_target is not None:
        return explicit_target.expanduser().resolve()

    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser().resolve() / "skills"

    return Path.home().expanduser().resolve() / ".codex" / "skills"


def resolve_install_mode(mode: str) -> str:
    if mode == "auto":
        return "copy" if platform.system() == "Windows" else "symlink"
    return mode


def load_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    skills = payload.get("skills", {})
    if not isinstance(skills, dict):
        return {}
    return {str(name): str(source) for name, source in skills.items()}


def write_manifest(path: Path, skills: dict[str, str]) -> None:
    payload = {
        "repo_root": str(REPO_ROOT.resolve()),
        "skills": skills,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    shutil.rmtree(path)


def is_repo_managed(dest: Path, skill_name: str, source: Path, manifest: dict[str, str]) -> bool:
    expected_source = str(source.resolve())
    if manifest.get(skill_name) == expected_source:
        return True
    if dest.is_symlink():
        try:
            return dest.resolve() == source.resolve()
        except OSError:
            return False
    return False


def install_skill(source: Path, dest: Path, mode: str) -> None:
    if mode == "symlink":
        dest.symlink_to(source.resolve(), target_is_directory=True)
        return
    shutil.copytree(source, dest)


def install_repo_skills(
    source_root: Path = SKILLS_ROOT,
    target_root: Path | None = None,
    mode: str = "auto",
) -> list[Path]:
    actual_target = resolve_target_root(target_root)
    actual_target.mkdir(parents=True, exist_ok=True)
    manifest_path = actual_target / MANIFEST_NAME
    manifest = load_manifest(manifest_path)
    install_mode = resolve_install_mode(mode)
    installed: list[Path] = []
    updated_manifest: dict[str, str] = {}

    for source in list_repo_skills(source_root):
        dest = actual_target / source.name
        if dest.exists() or dest.is_symlink():
            if is_repo_managed(dest, source.name, source, manifest):
                remove_path(dest)
            else:
                raise RuntimeError(
                    f"Refusing to replace unmanaged skill at {dest}. Move it aside or install to another target."
                )
        install_skill(source, dest, install_mode)
        updated_manifest[source.name] = str(source.resolve())
        installed.append(dest)

    write_manifest(manifest_path, updated_manifest)
    return installed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("auto", "copy", "symlink"),
        default="auto",
        help="Install mode. auto chooses copy on Windows and symlink elsewhere.",
    )
    parser.add_argument("--target", type=Path, help="Override target skills directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        installed = install_repo_skills(target_root=args.target, mode=args.mode)
        install_mode = resolve_install_mode(args.mode)
        target_root = resolve_target_root(args.target)
        for dest in installed:
            print(f"Installed {dest.name} -> {dest} ({install_mode})")
        print(f"Updated manifest at {target_root / MANIFEST_NAME}")
        return 0
    except RuntimeError as exc:
        print(f"Repo skill install failed: {exc}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, OSError) as exc:
        print(
            "Repo skill install failed while reading skill metadata or writing to the target directory: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
