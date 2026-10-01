from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(sys.platform != "win32", reason="run_algo.ps1 regression test is Windows-only")
def test_run_algo_skip_path_completes_without_lastexitcode_error() -> None:
    powershell = shutil.which("powershell")
    if not powershell:
        pytest.skip("powershell executable not available")

    result = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "run_algo.ps1"),
            "-SkipTraining",
            "-SkipWalkforward",
            "-SkipPaperSession",
            "-SkipPrecheck",
            "-SkipPromotionCheck",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Pipeline complete." in result.stdout
    assert "The variable '$LASTEXITCODE' cannot be retrieved because it has not been set." not in result.stderr

def test_python_fallback_passes_its_arguments() -> None:
    """In PowerShell command mode `-Arguments @(...) + $Arguments` binds only @(...) and
    silently drops $Arguments, so every fallback step ran with no arguments (config path,
    max splits and run dir ignored). The concatenation must stay inside parentheses."""
    text = (ROOT / "run_algo.ps1").read_text(encoding="utf-8")
    bare = re.compile(r"-Arguments\s+@\([^)]*\)\s*\+")
    assert not bare.search(text), "unparenthesised '-Arguments @(...) + $x' drops $x"
    assert '-Arguments (@("-c", $pyCode) + $Arguments)' in text


def test_resolve_python_prefers_venv_and_skips_store_stub() -> None:
    """The Microsoft Store 'python' placeholder (WindowsApps) is on PATH by default and
    exits 9009; the repo .venv must be tried first and the stub filtered out."""
    text = (ROOT / "run_algo.ps1").read_text(encoding="utf-8")
    body = text[text.index("function Resolve-PythonCommand"):text.index("function Invoke-Step")]
    assert body.index(".venv") < body.index("Get-Command python")
    assert "WindowsApps" in body
