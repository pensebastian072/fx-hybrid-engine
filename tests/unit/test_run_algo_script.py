from __future__ import annotations

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