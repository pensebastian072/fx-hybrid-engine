from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(relative_path: str, module_name: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNC_AGENT_DOCS = load_module("scripts/sync_agent_docs.py", "sync_agent_docs")
VALIDATE_REPO_SKILLS = load_module("scripts/validate_repo_skills.py", "validate_repo_skills")
INSTALL_REPO_SKILLS = load_module("scripts/install_repo_skills.py", "install_repo_skills")


def test_root_agents_has_no_legacy_command_refs() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "fxle-" not in text
    assert "pensebastian072/forex-engine" not in text


def test_generated_copilot_instructions_match_sync_script() -> None:
    agents_text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    expected = SYNC_AGENT_DOCS.render_copilot_instructions(agents_text)
    actual = (ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert actual == expected


def test_every_repo_skill_validates() -> None:
    assert VALIDATE_REPO_SKILLS.validate_skill_tree() == {}


def test_root_agents_contains_role_names() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for role_name in (
        "fxhy-architect",
        "fxhy-quant-engineer",
        "fxhy-ops-broker",
        "fxhy-review-validator",
    ):
        assert role_name in text


def test_legacy_quarantine_blocks_new_feature_work() -> None:
    text = (ROOT / "src" / "fx_lean_engine" / "AGENTS.md").read_text(encoding="utf-8")
    assert "Do not add new feature work here" in text


def test_ui_agents_points_to_real_dashboard_files() -> None:
    text = (ROOT / "ui" / "AGENTS.md").read_text(encoding="utf-8")
    assert "ui/src/lib/server-artifacts.ts" in text
    assert "ui/src/app/api/state/route.ts" in text
    assert "Next.js Admin Dashboard Starter" not in text


def test_repo_workflow_readmes_exist() -> None:
    required = [
        "docs/README.md",
        "skills/README.md",
        "skills/public/README.md",
        "skills/public/fxhy-architect/README.md",
        "skills/public/fxhy-quant-engineer/README.md",
        "skills/public/fxhy-ops-broker/README.md",
        "skills/public/fxhy-review-validator/README.md",
        "scripts/README.md",
        "src/README.md",
        "src/fx_hybrid_engine/README.md",
        "src/fx_lean_engine/README.md",
        "config/README.md",
        "tests/README.md",
        "ui/docs/README.md",
    ]
    for relative_path in required:
        assert (ROOT / relative_path).exists(), relative_path


def test_root_readme_links_folder_guides() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for relative_path in (
        "docs/README.md",
        "skills/README.md",
        "skills/public/README.md",
        "scripts/README.md",
        "src/README.md",
        "config/README.md",
        "tests/README.md",
        "ui/README.md",
    ):
        assert relative_path in text


def test_ui_readme_is_repo_specific() -> None:
    text = (ROOT / "ui" / "README.md").read_text(encoding="utf-8")
    assert "FX Hybrid Engine UI" in text
    assert "git clone https://github.com/Kiranism/next-shadcn-dashboard-starter.git" not in text
    assert "Admin Dashboard Starter Template" not in text


def test_install_repo_skills_copy_mode(tmp_path: Path) -> None:
    target = tmp_path / "skills"
    installed = INSTALL_REPO_SKILLS.install_repo_skills(target_root=target, mode="copy")
    installed_names = sorted(path.name for path in installed)
    assert installed_names == [
        "fxhy-architect",
        "fxhy-ops-broker",
        "fxhy-quant-engineer",
        "fxhy-review-validator",
    ]

    manifest = json.loads((target / INSTALL_REPO_SKILLS.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert sorted(manifest["skills"]) == installed_names
