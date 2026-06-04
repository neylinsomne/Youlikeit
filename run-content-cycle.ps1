
<#
.SYNOPSIS
  Content Cycle: 3 videos x 3 canales cada 3 dias.

.DESCRIPTION
  1. ex40 planea el batch (9 videos)
  2. Para cada video: ejecuta el pipeline con persona + tone
  3. Manda a review (ex15)
  4. Corre el learning cycle

.EXAMPLE
  .\run-content-cycle.ps1
  .\run-content-cycle.ps1 -Series "Berserk"
  .\run-content-cycle.ps1 -Persona deep_mind -DryRun
  .\run-content-cycle.ps1 -Theme "betrayal" -Series "Attack on Titan"
#>

param(
    [string]$Series = "",
    [string]$Persona = "",
    [string]$Theme = "",
    [switch]$DryRun,
    [switch]$SkipLearning,
    [switch]$UseDocker
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logsDir = Join-Path $PSScriptRoot "outputs\logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$logFile = Join-Path $logsDir "cycle_$timestamp.log"

function Write-Log {
    param([string]$Message, [string]$Color = "White")
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $logFile -Value $line
}

function Invoke-Ex {
    param([string]$Exercise, [string[]]$Args)
    $joinedArgs = ($Args -join " ")
    Write-Log "  Running $Exercise $joinedArgs" "DarkGray"
    if ($script:runInDocker) {
        $command = "python scripts/legacy/main.py $Exercise $joinedArgs"
        docker compose exec ytlab bash -lc $command
    } else {
        python scripts/legacy/main.py $Exercise @Args
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "  WARN: $Exercise returned exit code $LASTEXITCODE" "Yellow"
    }
}

function Set-PersonaDataContext {
    param([string]$PersonaName)

    if (-not $PersonaName) {
        $env:DATA_DIR = "data"
        return
    }

    $personaDataDir = Join-Path $PSScriptRoot ("data\\personas\\" + $PersonaName)
    New-Item -ItemType Directory -Force -Path $personaDataDir | Out-Null
    $env:DATA_DIR = $personaDataDir
}

function Set-PersonaChannelContext {
    param([string]$PersonaName)

    if (-not $PersonaName) {
        return
    }

    $personasPath = Join-Path $PSScriptRoot "tokens\personas.json"
    if (-not (Test-Path $personasPath)) {
        return
    }

    try {
        $personasCfg = Get-Content $personasPath -Raw | ConvertFrom-Json
        $entry = $personasCfg.$PersonaName
        if ($null -ne $entry -and $null -ne $entry.youtube -and $entry.youtube.channel_id) {
            $env:YOUTUBE_CHANNEL_ID = [string]$entry.youtube.channel_id
            Write-Log "  YOUTUBE_CHANNEL_ID: $($env:YOUTUBE_CHANNEL_ID)" "DarkGray"
        }
    } catch {
        Write-Log "  WARN: No se pudo leer tokens/personas.json para $PersonaName" "Yellow"
    }
}

# Detect execution mode
$script:runInDocker = $false
if ($UseDocker) {
    $script:runInDocker = $true
    docker compose up -d ytlab | Out-Null
} elseif (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    $script:runInDocker = $true
    docker compose up -d ytlab | Out-Null
}

Write-Log "===== CONTENT CYCLE START =====" "Cyan"
Write-Log "Mode: $(if ($script:runInDocker) {'Docker'} else {'Local'})"
Write-Log "Series: $(if ($Series) {$Series} else {'auto'})"
Write-Log "Persona: $(if ($Persona) {$Persona} else {'all (deep_mind, cinephile, pop_oracle)'})"

# ── Step 1: Plan the batch ──

Write-Log ""
Write-Log "STEP 1: PLANNING BATCH" "Yellow"

$planArgs = @()
if ($Series)  { $planArgs += @("--series", "`"$Series`"") }
if ($Persona) { $planArgs += @("--persona", $Persona) }
if ($Theme)   { $planArgs += @("--theme", "`"$Theme`"") }
if ($DryRun)  { $planArgs += @("--dry-run") }

Invoke-Ex "ex40" $planArgs

if ($DryRun) {
    Write-Log "DRY RUN — stopping here." "Yellow"
    exit 0
}

# ── Step 2: Load and execute each planned video ──

Write-Log ""
Write-Log "STEP 2: PRODUCING VIDEOS" "Yellow"

# Read the latest batch plan JSON
$scheduleDir = Join-Path $PSScriptRoot "outputs\schedule"
$latestPlan = Get-ChildItem -Path $scheduleDir -Filter "batch_plan_*.json" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $latestPlan) {
    Write-Log "ERROR: No batch plan found. Run ex40 first." "Red"
    exit 1
}

$batch = Get-Content $latestPlan.FullName | ConvertFrom-Json
Write-Log "Loaded batch: $($latestPlan.Name) ($($batch.Count) videos)"

$videoNum = 0
foreach ($video in $batch) {
    $videoNum++
    $p = $video.persona
    $vt = $video.video_type
    $q = $video.query
    $tone = $video.tone
    $style = $video.style

    Write-Log ""
    Write-Log "── VIDEO $videoNum/$($batch.Count): $($p.ToUpper()) / $($vt.ToUpper()) ──" "Green"
    Write-Log "  Theme: $($video.theme) | Tone: $tone | Style: $style | Affinity: $($video.affinity)"

    # Isolate DB + RAG (Chroma under DATA_DIR) per persona
    Set-PersonaDataContext -PersonaName $p
    Set-PersonaChannelContext -PersonaName $p
    Write-Log "  DATA_DIR: $($env:DATA_DIR)" "DarkGray"

    # Content discovery (shared across types — cached by ex04-ex06)
    Write-Log "  [discover]" "DarkGray"
    Invoke-Ex "ex04" @("--query", "`"$q`"", "--max-movies", "12", "--mode", "trending")
    Invoke-Ex "ex05" @("--max-downloads", "12")
    Invoke-Ex "ex06" @("--threshold", "72", "--with-chroma")
    Invoke-Ex "ex10" @("--provider", "auto", "--batch-size", "50")

    # Build + cut
    Write-Log "  [build]" "DarkGray"
    Invoke-Ex "ex07" @("--query", "`"$q`"", "--max-results", "5")
    Invoke-Ex "ex09" @("--query", "`"$q`"", "--max-results", "5", "--group-size", "3")
    Invoke-Ex "ex11" @("--query", "`"$q`"", "--burn-subs")

    # Narrate with persona + tone
    Write-Log "  [narrate: $p / $style]" "DarkGray"
    Invoke-Ex "ex18" @("--query", "`"$q`"", "--lang", "en", "--narration-style", $style, "--persona", $p)

    # Growth + strategy
    Write-Log "  [strategy]" "DarkGray"
    Invoke-Ex "ex08" @("--query", "`"$q`"", "--country-code", "US", "--period-days", "7")
    Invoke-Ex "ex13" @("--query", "`"$q`"")
    Invoke-Ex "ex17" @("--query", "`"$q`"", "--platform", "both", "--country-code", "US")

    Write-Log "  DONE: $p / $vt / $tone" "Green"
}

# ── Step 3: Review ──

Write-Log ""
Write-Log "STEP 3: REVIEW READY" "Yellow"
Write-Log "  Open review dashboard: http://localhost:8000"
Write-Log "  From there you can approve + upload to YouTube/TikTok per persona"

# ── Step 4: Learning cycle ──

if (-not $SkipLearning) {
    Write-Log ""
    Write-Log "STEP 4: LEARNING CYCLE" "Yellow"

    $learningPersonas = @($batch | Select-Object -ExpandProperty persona -Unique)
    foreach ($lp in $learningPersonas) {
        Write-Log "  [learning: $lp]" "DarkGray"
        Set-PersonaDataContext -PersonaName $lp
        Set-PersonaChannelContext -PersonaName $lp
        Write-Log "  DATA_DIR: $($env:DATA_DIR)" "DarkGray"

        Invoke-Ex "ex19" @("--days-back", "30")
        Invoke-Ex "ex24" @("--days-back", "30")
        Invoke-Ex "ex21" @("--min-samples", "3")
        Invoke-Ex "ex22" @("--ab-action", "auto")
        Invoke-Ex "ex23" @()
    }

    Write-Log "  Learning cycle complete." "Green"
}

# ── Sync to USB ──

if (Test-Path "E:\") {
    Write-Log ""
    Write-Log "SYNCING TO USB E:..." "DarkGray"
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "sync-to-usb.ps1")
}

Write-Log ""
Write-Log "===== CONTENT CYCLE COMPLETE =====" "Cyan"
Write-Log "Log: $logFile"
Write-Log ""
Write-Log "Next steps:" "White"
Write-Log "  1. Open review: http://localhost:8000" "White"
Write-Log "  2. Review + approve shorts" "White"
Write-Log "  3. Upload via dashboard (YT + TT buttons per persona)" "White"
Write-Log "  4. Run this again in 3 days" "White"
