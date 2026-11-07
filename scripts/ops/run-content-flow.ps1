param(
    [string]$Query = "epic villain moment",
    [string]$CountryCode = "CO",
    [int]$PeriodDays = 7,
    [int]$MaxMovies = 12,
    [int]$MaxDownloads = 12,
    [int]$Threshold = 72,
    [int]$MaxResults = 5,
    [int]$GroupSize = 3,
    [switch]$UseDocker,
    [switch]$SkipConnectionCheck
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $RepoRoot

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logsDir = Join-Path $RepoRoot "outputs\logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$logFile = Join-Path $logsDir "flow_$timestamp.log"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

function Invoke-Exercise {
    param([string]$Exercise, [string[]]$Args)

    $joinedArgs = ($Args -join " ")
    Write-Log "Running $Exercise $joinedArgs"

    if ($script:runInDocker) {
        $command = "python scripts/legacy/main.py $Exercise $joinedArgs"
        docker compose exec ytlab bash -lc $command
    }
    else {
        python scripts/legacy/main.py $Exercise @Args
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Exercise"
    }
}

# Auto-detect execution mode.
$script:runInDocker = $false
if ($UseDocker) {
    $script:runInDocker = $true
}
else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        $script:runInDocker = $true
    }
}

if ($script:runInDocker) {
    Write-Log "Execution mode: Docker"
    docker compose up -d ytlab | Out-Null
}
else {
    Write-Log "Execution mode: Local Python"
}

Write-Log "Flow started. Query='$Query'"

if (-not $SkipConnectionCheck) {
    Invoke-Exercise "ex00" @()
}

Invoke-Exercise "ex04" @("--query", "`"$Query`"", "--max-movies", "$MaxMovies", "--mode", "trending")
Invoke-Exercise "ex05" @("--max-downloads", "$MaxDownloads")
Invoke-Exercise "ex06" @("--threshold", "$Threshold", "--with-chroma")
Invoke-Exercise "ex10" @("--provider", "auto", "--batch-size", "50")
Invoke-Exercise "ex07" @("--query", "`"$Query`"", "--max-results", "$MaxResults")
Invoke-Exercise "ex09" @("--query", "`"$Query`"", "--max-results", "$MaxResults", "--group-size", "$GroupSize")
Invoke-Exercise "ex11" @("--query", "`"$Query`"", "--burn-subs")
Invoke-Exercise "ex08" @("--query", "`"$Query`"", "--country-code", "$CountryCode", "--period-days", "$PeriodDays")
Invoke-Exercise "ex18" @("--query", "`"$Query`"", "--lang", "es", "--narration-style", "reflective")
Invoke-Exercise "ex13" @("--query", "`"$Query`"")
Invoke-Exercise "ex17" @("--query", "`"$Query`"", "--platform", "both", "--country-code", "$CountryCode")

# Learning cycle (runs after publish, feeds back into next cycle)
Invoke-Exercise "ex19" @("--days-back", "30")
Invoke-Exercise "ex24" @("--days-back", "30")
Invoke-Exercise "ex26" @("--days-back", "30")
Invoke-Exercise "ex20" @("--query", "`"$Query`"", "--max-results", "15")
Invoke-Exercise "ex25" @("--target", "impressions")
Invoke-Exercise "ex21" @("--min-samples", "3")
Invoke-Exercise "ex22" @("--ab-action", "auto")
Invoke-Exercise "ex23" @()
Invoke-Exercise "ex31" @("--batch-size", "50")
Invoke-Exercise "ex32" @()
Invoke-Exercise "ex33" @()

Write-Log "Flow completed successfully."
Write-Log "Output logs: $logFile"

# Sync outputs to USB E: (if connected)
if (Test-Path "E:\") {
    Write-Log "Syncing outputs to USB E:..."
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "sync-to-usb.ps1")
    Write-Log "USB sync done."
} else {
    Write-Log "USB E: not connected, skipping sync."
}
