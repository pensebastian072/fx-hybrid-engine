<#
.SYNOPSIS
  Export unpushed commits as a patch file so Copilot can apply and push them.

.USAGE
  From the Codex / local terminal (in the repo root):
    powershell -File scripts\export_for_copilot.ps1

  This writes changes to: C:\path\to\.copilot\pending_patch.patch
  Then tell Copilot: "apply the pending patch and push"
#>

$repoRoot = Split-Path -Parent $PSScriptRoot
$outFile   = "$HOME\.copilot\pending_patch.patch"

Push-Location $repoRoot

# Ensure origin is set
git remote set-url origin https://github.com/pensebastian072/forex-engine.git 2>$null

# Write format-patch to file
git format-patch origin/work..work --stdout | Set-Content -Path $outFile -Encoding UTF8

$count = (git log --oneline origin/work..work | Measure-Object -Line).Lines
Write-Host "Exported $count commit(s) to: $outFile"
Write-Host "Now tell Copilot: 'apply the pending patch and push'"

Pop-Location
