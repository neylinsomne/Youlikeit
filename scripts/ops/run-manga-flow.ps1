# ============================================================
# run-manga-flow.ps1 — Pipeline completo de manga/anime Shorts
# Un solo click: descubre → clasifica → scrape wiki → OCR → video → metadata
# ============================================================
param(
    [string]$MediaType = "all",          # anime, manga, all
    [int]$MaxSeries = 15,                # series a descubrir
    [string]$SeriesTitle = "",           # titulo especifico (opcional, para ex38/ex39)
    [string]$Source = "",                # imagen/CBZ para OCR (opcional)
    [string]$ReadingOrder = "rtl",       # rtl=manga, ltr=manhwa
    [string]$Lang = "en",               # idioma narración
    [string]$CountryCode = "CO",        # pais para trending
    [switch]$SkipDiscovery,             # saltar ex36 si ya se descubrió
    [switch]$SkipOCR,                   # saltar ex38 si no hay imagenes
    [switch]$DryRun                     # solo mostrar qué haría
)

$ErrorActionPreference = "Stop"$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $RepoRoot

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "=== MANGA/ANIME SHORTS PIPELINE ===" -ForegroundColor Cyan
Write-Host "Started: $ts" -ForegroundColor Gray
Write-Host ""

function Run-Step {
    param([string]$Name, [string]$Cmd)
    Write-Host "[$Name]" -ForegroundColor Yellow -NoNewline
    Write-Host " Running..." -ForegroundColor Gray
    if ($DryRun) {
        Write-Host "  (dry-run) $Cmd" -ForegroundColor DarkGray
        return
    }
    $result = docker compose exec ytlab $Cmd.Split(" ") 2>&1
    $exit = $LASTEXITCODE
    if ($exit -eq 0) {
        Write-Host "  OK" -ForegroundColor Green
    } else {
        Write-Host "  FAILED (exit=$exit)" -ForegroundColor Red
        $result | Select-Object -Last 3 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkRed }
    }
    return $result
}

# ---- FASE 1: Descubrir ----
if (-not $SkipDiscovery) {
    Run-Step "ex36 Discover" "python scripts/legacy/main.py ex36 --media-type $MediaType --max-movies $MaxSeries"
}

# ---- FASE 2: Clasificar ----
Run-Step "ex37 Classify" "python scripts/legacy/main.py ex37 --provider auto --batch-size 50"

# ---- FASE 3: Wiki Scrape (si hay titulo) ----
if ($SeriesTitle) {
    Run-Step "ex39 Wiki Scrape" "python scripts/legacy/main.py ex39 --series-title `"$SeriesTitle`" --max-pages 10"
}

# ---- FASE 4: OCR + Video (si hay source) ----
if ($Source -and -not $SkipOCR) {
    Run-Step "ex38 OCR+Video" "python scripts/legacy/main.py ex38 --source $Source --series-title `"$SeriesTitle`" --reading-order $ReadingOrder"
}

# ---- FASE 5: Growth Pack (hashtags + canciones trending) ----
$query = if ($SeriesTitle) { "$SeriesTitle anime quotes" } else { "anime manga trending quotes" }
Run-Step "ex08 Growth Pack" "python scripts/legacy/main.py ex08 --query `"$query`" --country-code $CountryCode"

# ---- FASE 6: Narración ----
Run-Step "ex18 Narration" "python scripts/legacy/main.py ex18 --query `"$query`" --lang $Lang --narration-style dramatic"

# ---- FASE 7: Estrategia de publicación ----
Run-Step "ex17 Publish Strategy" "python scripts/legacy/main.py ex17 --query `"$query`" --platform both --country-code $CountryCode --lang $Lang"

# ---- RESUMEN ----
Write-Host ""
Write-Host "=== PIPELINE COMPLETE ===" -ForegroundColor Cyan
Write-Host "Outputs:" -ForegroundColor Gray
Write-Host "  Logs:      outputs/logs/ex36_*, ex37_*, ex39_*"
Write-Host "  Video:     outputs/manga/*_short.mp4"
Write-Host "  Metadata:  outputs/metadata/ex08_growth_pack_*.json"
Write-Host "  Narration: outputs/narration/*/"
Write-Host "  Strategy:  outputs/publish/ex17_strategy_*.json"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Review video in outputs/manga/"
Write-Host "  2. Select trending song ON PLATFORM (15-25% volume)"
Write-Host "  3. Upload: python scripts/legacy/main.py ex12 --video outputs/manga/...mp4"
Write-Host ""
$ts2 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "Finished: $ts2" -ForegroundColor Gray
