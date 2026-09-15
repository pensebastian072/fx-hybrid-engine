param(
    [string]$ConfigPath = "config/default.yaml",
    [string]$WfRunId = "",
    [string]$PaperRunId = "",
    [string]$PaperRunDir = "",
    [string]$Rail = "",
    [ValidateSet("local_paper", "scaffold", "qc_push")]
    [string]$ExecutionProfile = "local_paper",
    [int]$MaxSplits = 1,
    [int]$PaperRunSeconds = 60,
    [switch]$InstallDeps,
    [switch]$SkipTraining,
    [switch]$SkipWalkforward,
    [switch]$SkipPaperSession,
    [switch]$SkipPrecheck,
    [switch]$SkipPromotionCheck,
    [switch]$FullRobustness,
    [switch]$RunLivePrecheck,
    [switch]$StartLiveRail,
    [switch]$PushQCPaper
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-PythonCommand {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCmd) {
        return $pythonCmd.Source
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyCmd) {
        return $pyCmd.Source
    }

    $candidates = @(
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        "$env:LocalAppData\Programs\Python\Python312\python.exe",
        "$env:LocalAppData\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "Python executable not found. Install Python or add it to PATH before running run_algo.ps1."
}

function Invoke-Step {
    param(
        [string]$Title,
        [string]$Command,
        [string[]]$Arguments
    )
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
    Write-Host "$Command $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Title (exit code $LASTEXITCODE)"
    }
}

function Ensure-Command {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    return $null -ne $cmd
}

function Test-PythonImport {
    param([string]$ModuleName)

    try {
        $pythonCmd = Resolve-PythonCommand
    }
    catch {
        return $false
    }

    try {
        & $pythonCmd -c "import $ModuleName" *> $null
    }
    catch {
        return $false
    }

    if ($?) {
        return $true
    }

    if (Test-Path variable:LASTEXITCODE) {
        return ($LASTEXITCODE -eq 0)
    }

    return $false
}

function Ensure-FxhePackage {
    if (Test-PythonImport -ModuleName "fx_hybrid_engine") {
        return
    }
    Invoke-Step -Title "Install Dependencies (auto)" -Command $script:PythonCommand -Arguments @("-m", "pip", "install", "-e", ".[dev]")
    if (-not (Test-PythonImport -ModuleName "fx_hybrid_engine")) {
        throw "Unable to import fx_hybrid_engine even after install."
    }
}

function Ensure-ParquetEngine {
    if (Test-PythonImport -ModuleName "pyarrow") {
        return
    }
    Invoke-Step -Title "Install PyArrow (parquet support)" -Command $script:PythonCommand -Arguments @("-m", "pip", "install", "pyarrow")
}

$FxheEntrypoints = @{
    "fxhe-train" = "main_train"
    "fxhe-walkforward" = "main_walkforward"
    "fxhe-report" = "main_report"
    "fxhe-paper-session" = "main_paper_session"
    "fxhe-local-paper" = "main_local_paper"
    "fxhe-phase6-precheck" = "main_phase6_precheck"
    "fxhe-promote-check" = "main_promote_check"
    "fxhe-live-precheck" = "main_live_precheck"
    "fxhe-live" = "main_live"
}

function Invoke-Fxhe {
    param(
        [string]$FxheCommand,
        [string]$Title,
        [string[]]$Arguments
    )
    if (Ensure-Command $FxheCommand) {
        Invoke-Step -Title $Title -Command $FxheCommand -Arguments $Arguments
        return
    }
    if (-not $FxheEntrypoints.ContainsKey($FxheCommand)) {
        throw "Unknown fxhe command for fallback invocation: $FxheCommand"
    }
    $entry = $FxheEntrypoints[$FxheCommand]
    $pyCode = "import sys; from fx_hybrid_engine.cli import $entry as f; sys.argv=['$FxheCommand'] + sys.argv[1:]; f()"
    Invoke-Step -Title "$Title (python fallback)" -Command $script:PythonCommand -Arguments @("-c", $pyCode) + $Arguments
}

$repoRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$script:PythonCommand = Resolve-PythonCommand
Push-Location $repoRoot
try {
    if ([string]::IsNullOrWhiteSpace($WfRunId)) {
        $WfRunId = "wf_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
    }
    if ([string]::IsNullOrWhiteSpace($PaperRunId)) {
        $PaperRunId = "paper_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
    }
    if ($PushQCPaper) {
        $ExecutionProfile = "qc_push"
    }

    if ($InstallDeps) {
        Invoke-Step -Title "Install Dependencies" -Command $script:PythonCommand -Arguments @("-m", "pip", "install", "-e", ".[dev]")
    }

    Ensure-FxhePackage
    Ensure-ParquetEngine

    if (-not $SkipTraining) {
        Invoke-Fxhe -FxheCommand "fxhe-train" -Title "Train Models (Trend + HMM)" -Arguments @("--config", $ConfigPath)
    }

    if (-not $SkipWalkforward) {
        $wfArgs = @(
            "--config", $ConfigPath,
            "--run-id", $WfRunId,
            "--max-splits", "$MaxSplits"
        )
        if (-not $FullRobustness) {
            $wfArgs += "--skip-robustness"
        }
        Invoke-Fxhe -FxheCommand "fxhe-walkforward" -Title "Walk-Forward Evaluation" -Arguments $wfArgs
        Invoke-Fxhe -FxheCommand "fxhe-report" -Title "Generate Phase 5 Report" -Arguments @("--config", $ConfigPath, "--wf-run-id", $WfRunId)
    }

    if ([string]::IsNullOrWhiteSpace($PaperRunDir)) {
        $utcDate = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
        $PaperRunDir = Join-Path -Path "outputs/paper/$utcDate" -ChildPath $PaperRunId
    }

    if (-not $SkipPaperSession) {
        switch ($ExecutionProfile) {
            "local_paper" {
                Invoke-Fxhe -FxheCommand "fxhe-local-paper" -Title "Run Local Paper Session" -Arguments @(
                    "--config", $ConfigPath,
                    "--run-id", $PaperRunId,
                    "--output-dir", $PaperRunDir,
                    "--run-seconds", "$PaperRunSeconds"
                )
            }
            "scaffold" {
                Invoke-Fxhe -FxheCommand "fxhe-paper-session" -Title "Bootstrap Paper Session" -Arguments @(
                    "--config", $ConfigPath,
                    "--run-id", $PaperRunId,
                    "--output-dir", $PaperRunDir,
                    "--run-seconds", "$PaperRunSeconds"
                )
            }
            "qc_push" {
                Invoke-Fxhe -FxheCommand "fxhe-live" -Title "Push QC Paper Session" -Arguments @(
                    "--config", $ConfigPath,
                    "--paper"
                )
            }
        }
    }

    $EffectiveRail = $Rail
    if ([string]::IsNullOrWhiteSpace($EffectiveRail)) {
        switch ($ExecutionProfile) {
            "local_paper" { $EffectiveRail = "local_paper" }
            "scaffold" { $EffectiveRail = "paper_scaffold" }
            default { $EffectiveRail = "" }
        }
    }

    if (-not $SkipPrecheck -and $ExecutionProfile -ne "qc_push") {
        $phase6Args = @(
            "--config", $ConfigPath,
            "--run-dir", $PaperRunDir
        )
        if (-not [string]::IsNullOrWhiteSpace($EffectiveRail)) {
            $phase6Args += @("--rail", $EffectiveRail)
        }
        Invoke-Fxhe -FxheCommand "fxhe-phase6-precheck" -Title "Phase 6 Precheck" -Arguments $phase6Args
    } elseif (-not $SkipPrecheck -and $ExecutionProfile -eq "qc_push") {
        Write-Host "Skipping Phase 6 Precheck for qc_push profile (no local paper run dir)." -ForegroundColor Yellow
    }

    if (-not $SkipPromotionCheck -and -not $SkipWalkforward -and $ExecutionProfile -ne "qc_push") {
        Invoke-Fxhe -FxheCommand "fxhe-promote-check" -Title "Promotion Check" -Arguments @(
            "--config", $ConfigPath,
            "--wf-id", $WfRunId,
            "--paper-run-dir", $PaperRunDir
        )
    } elseif (-not $SkipPromotionCheck -and -not $SkipWalkforward -and $ExecutionProfile -eq "qc_push") {
        Write-Host "Skipping Promotion Check for qc_push profile (no local paper artifacts)." -ForegroundColor Yellow
    }

    if ($RunLivePrecheck) {
        Invoke-Fxhe -FxheCommand "fxhe-live-precheck" -Title "Live Precheck" -Arguments @("--config", $ConfigPath)
    }

    if ($StartLiveRail -or $PushQCPaper) {
        Invoke-Fxhe -FxheCommand "fxhe-live" -Title "Start configured live rail" -Arguments @(
            "--config", $ConfigPath,
            "--paper"
        )
    }

    Write-Host ""
    Write-Host "Pipeline complete." -ForegroundColor Green
    Write-Host "Execution profile: $ExecutionProfile"
    Write-Host "Walkforward run: artifacts/walkforward/$WfRunId"
    Write-Host "Paper run dir:   $PaperRunDir"

    # Normalize artifacts for UI dashboard
    Write-Host ""
    Write-Host "=== Normalizing artifacts for UI ===" -ForegroundColor Cyan
    $normalizeArgs = @("scripts/normalize_artifacts.py", "--wf-run-id", $WfRunId)
    if ((Test-Path $PaperRunDir) -and $ExecutionProfile -ne "qc_push") {
        $normalizeArgs += @("--paper-run-dir", $PaperRunDir)
    }
    & $script:PythonCommand @normalizeArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "normalize_artifacts.py exited with code $LASTEXITCODE — UI artifacts may be stale."
    } else {
        Write-Host "UI artifacts written to artifacts/latest_run/" -ForegroundColor Green
    }

    Write-Host "=== Running SHAP trade analysis ===" -ForegroundColor Cyan
    & $script:PythonCommand scripts/analyze_trades.py
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "analyze_trades.py exited with code $LASTEXITCODE — trade analysis skipped."
    } else {
        Write-Host "Trade analysis written to artifacts/latest_run/trade_analysis.json" -ForegroundColor Green
    }
}
finally {
    Pop-Location
}
