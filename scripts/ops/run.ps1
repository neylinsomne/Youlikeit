# ============================================================
# run.ps1 — Punto de entrada unico para TODOS los pipelines
# ============================================================
# Uso:
#   .\run.ps1 manga                          # manga pipeline completo
#   .\run.ps1 manga -SeriesTitle "Berserk"   # manga con wiki scrape
#   .\run.ps1 movies                         # pipeline de peliculas
#   .\run.ps1 movies -Query "villain quotes" # peliculas con query
#   .\run.ps1 learn                          # ciclo de aprendizaje
#   .\run.ps1 dashboard                      # levantar dashboard
#   .\run.ps1 status                         # ver estado de la BD
# ============================================================
param(
    [Parameter(Position=0)]
    [ValidateSet("manga", "movies", "learn", "dashboard", "status", "upload")]
    [string]$Pipeline = "status",

    # Comunes
    [string]$Query = "",
    [string]$CountryCode = "CO",
    [string]$Lang = "en",

    # Manga
    [string]$MediaType = "all",
    [int]$MaxSeries = 15,
    [string]$SeriesTitle = "",
    [string]$Source = "",
    [string]$ReadingOrder = "rtl",

    # Movies
    [int]$MaxMovies = 12,
    [string]$Mode = "trending",

    # Upload
    [string]$Video = "",
    [string]$Title = "",
    [string]$Privacy = "private",

    # Control
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $RepoRoot

function Docker-Run {
    param([string]$Step, [string[]]$Args)
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] " -ForegroundColor DarkGray -NoNewline
    Write-Host "$Step" -ForegroundColor Yellow -NoNewline
    Write-Host " ..." -ForegroundColor Gray

    if ($DryRun) {
        Write-Host "  (dry-run) python scripts/legacy/main.py $($Args -join ' ')" -ForegroundColor DarkGray
        return $true
    }

    $allArgs = @("compose", "exec", "ytlab", "python", "scripts/legacy/main.py") + $Args
    & docker $allArgs 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    $ok = $LASTEXITCODE -eq 0
    if ($ok) { Write-Host "  OK" -ForegroundColor Green }
    else     { Write-Host "  FAILED" -ForegroundColor Red }
    return $ok
}

# Verificar que Docker esta corriendo
$running = docker compose ps --format json 2>$null | ConvertFrom-Json | Where-Object { $_.Service -eq "ytlab" -and $_.State -eq "running" }
if (-not $running -and -not $DryRun) {
    Write-Host "Starting Docker containers..." -ForegroundColor Yellow
    docker compose up -d ytlab 2>&1 | Out-Null
    Start-Sleep 3
}

Write-Host ""
Write-Host "=== YOULIKEIT PIPELINE: $($Pipeline.ToUpper()) ===" -ForegroundColor Cyan
Write-Host ""

switch ($Pipeline) {
    "manga" {
        # Paso 1: Descubrir trending
        Docker-Run "Discover trending $MediaType" @("ex36", "--media-type", $MediaType, "--max-movies", $MaxSeries)

        # Paso 2: Clasificar quotes
        Docker-Run "Classify quotes" @("ex37", "--provider", "auto", "--batch-size", "50")

        # Paso 3: Wiki scrape (si hay titulo)
        if ($SeriesTitle) {
            Docker-Run "Wiki scrape: $SeriesTitle" @("ex39", "--series-title", $SeriesTitle, "--max-pages", "10")
        }

        # Paso 4: OCR + Ken Burns video (si hay source)
        if ($Source) {
            Docker-Run "OCR + Video" @("ex38", "--source", $Source, "--series-title", $SeriesTitle, "--reading-order", $ReadingOrder)
        }

        # Paso 5: Growth pack
        $q = if ($SeriesTitle) { "$SeriesTitle anime quotes" } else { "anime manga trending" }
        Docker-Run "Growth pack" @("ex08", "--query", $q, "--country-code", $CountryCode)

        # Paso 6: Narracion
        Docker-Run "Narration" @("ex18", "--query", $q, "--lang", $Lang, "--narration-style", "dramatic")

        # Paso 7: Estrategia de publicacion
        Docker-Run "Publish strategy" @("ex17", "--query", $q, "--platform", "both", "--country-code", $CountryCode, "--lang", $Lang)
    }

    "movies" {
        $q = if ($Query) { $Query } else { "epic villain moment" }

        Docker-Run "Discover movies" @("ex04", "--max-movies", $MaxMovies, "--mode", $Mode)
        Docker-Run "Download subtitles" @("ex05", "--max-downloads", $MaxMovies)
        Docker-Run "Match quotes" @("ex06", "--threshold", "72", "--with-chroma")
        Docker-Run "Classify quotes" @("ex10", "--batch-size", "50")
        Docker-Run "Search scenes" @("ex07", "--query", $q, "--max-results", "5")
        Docker-Run "Curate groups" @("ex09", "--query", $q, "--max-results", "5", "--group-size", "3")
        Docker-Run "Cut video" @("ex11", "--query", $q, "--burn-subs")
        Docker-Run "Growth pack" @("ex08", "--query", $q, "--country-code", $CountryCode)
        Docker-Run "Narration" @("ex18", "--query", $q, "--lang", $Lang)
        Docker-Run "Publish strategy" @("ex17", "--query", $q, "--platform", "both", "--country-code", $CountryCode, "--lang", $Lang)
    }

    "learn" {
        Docker-Run "Lesson taxonomy" @("ex31", "--batch-size", "50")
        Docker-Run "Lesson performance" @("ex32")
        Docker-Run "Curriculum planner" @("ex33", "--plan-size", "10")
        Docker-Run "Analytics" @("ex19", "--days-back", "30")
        Docker-Run "Algorithm signals" @("ex25", "--target", "impressions")
        Docker-Run "Demographics" @("ex26", "--days-back", "30")
        Docker-Run "Auto-adjust" @("ex21")
    }

    "dashboard" {
        Write-Host "Starting services..." -ForegroundColor Yellow
        docker compose up -d 2>&1 | Out-Null
        Start-Sleep 3
        Write-Host "Dashboard:  http://localhost:8080" -ForegroundColor Green
        Write-Host "API:        http://localhost:8001" -ForegroundColor Green
        Write-Host "Frontend:   http://localhost:8002/app" -ForegroundColor Green
    }

    "upload" {
        if (-not $Video) {
            Write-Host "Error: --Video required" -ForegroundColor Red
            return
        }
        $t = if ($Title) { $Title } else { "Short" }
        Docker-Run "Upload" @("ex12", "--video", $Video, "--title", $t, "--privacy", $Privacy)
    }

    "status" {
        docker compose exec ytlab python -c @"
import sqlite3
conn = sqlite3.connect('data/shorts_pipeline.db')
conn.row_factory = sqlite3.Row
print('=== DATABASE STATUS ===')
for t in ['movies','quotes','manga_series','manga_quotes','shorts','analytics']:
    try:
        r = conn.execute(f'SELECT COUNT(*) as n FROM {t}').fetchone()
        print(f'  {t}: {r[\"n\"]} rows')
    except: pass
print()
r = conn.execute('SELECT COUNT(*) as n FROM quotes WHERE start_ms IS NOT NULL').fetchone()
print(f'  Quotes with timestamps: {r[\"n\"]}')
r = conn.execute('SELECT COUNT(*) as n FROM quotes WHERE category IS NOT NULL').fetchone()
print(f'  Quotes classified: {r[\"n\"]}')
try:
    r = conn.execute('SELECT COUNT(*) as n FROM manga_quotes WHERE category IS NOT NULL').fetchone()
    print(f'  Manga quotes classified: {r[\"n\"]}')
except: pass
"@
    }
}

Write-Host ""
Write-Host "=== DONE ===" -ForegroundColor Cyan
