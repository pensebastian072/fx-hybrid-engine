# vendor_setup.ps1 — Clone ML4T vendor repositories to vendor/
# Usage: .\scripts\vendor_setup.ps1
#
# Run once per machine (or after a fresh clone).  vendor/ is git-ignored.
# After cloning, run: python scripts/vendor_check.py

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    if (-not (Test-Path "vendor")) {
        New-Item -ItemType Directory -Path "vendor" | Out-Null
    }

    $repos = @(
        @{ Dir = "vendor/ml4t-jansen"; Url = "https://github.com/stefan-jansen/machine-learning-for-trading.git" },
        @{ Dir = "vendor/ml4t-gatech"; Url = "https://github.com/cwu392/Machine-Learning-for-Trading.git" }
    )

    foreach ($repo in $repos) {
        if (Test-Path $repo.Dir) {
            Write-Host "Already exists: $($repo.Dir) — skipping clone."
        } else {
            Write-Host "Cloning $($repo.Url) → $($repo.Dir) ..."
            git clone --depth=1 $repo.Url $repo.Dir
        }
    }

    Write-Host ""
    Write-Host "Done. Run: python scripts/vendor_check.py"
} finally {
    Pop-Location
}
