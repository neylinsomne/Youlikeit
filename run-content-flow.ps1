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
Set-Location $PSScriptRoot

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logsDir = Join-Path $PSScriptRoot "outputs\logs"
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
        $command = "python src/main.py $Exercise $joinedArgs"
        docker compose exec ytlab bash -lc $command
    }
    else {
        python src/main.py $Exercise @Args
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
Invoke-Exercise "ex13" @("--query", "`"$Query`"")

Write-Log "Flow completed successfully."
Write-Log "Output logs: $logFile"
