# run_tests.ps1 — runner unificado para Windows PowerShell.
#
# Uso:
#   .\scripts\run_tests.ps1                # quick: unit + integration, sin coverage
#   .\scripts\run_tests.ps1 -Mode coverage # con coverage HTML en htmlcov/
#   .\scripts\run_tests.ps1 -Mode e2e      # solo e2e (mas lento)
#   .\scripts\run_tests.ps1 -Mode all      # todo + coverage + verify_signals_flow
#   .\scripts\run_tests.ps1 -Install       # instala dev deps antes
#
# Filosofia: 1 comando = 1 fase. Output con colores. Devuelve exit code.

[CmdletBinding()]
param(
    [ValidateSet("quick", "unit", "integration", "e2e", "coverage", "all")]
    [string]$Mode = "quick",

    [switch]$Install,

    [switch]$Detailed
)

$ErrorActionPreference = "Stop"

function Write-Section($title) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $title" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Write-Ok($msg)   { Write-Host "  [OK]  $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Write-Skip($msg) { Write-Host "  [SKIP] $msg" -ForegroundColor Yellow }

# Asegura cwd = root del repo
$ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $ROOT

if ($Install) {
    Write-Section "Instalando dependencias de testing"
    python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { Write-Fail "pip install fallo"; exit 1 }
    Write-Ok "deps instaladas"
}

# Verbosity flag para pytest
$VFlag = if ($Detailed) { "-vv" } else { "-q" }

switch ($Mode) {
    "quick" {
        Write-Section "Tests rapidos (unit + integration)"
        python -m pytest $VFlag -m "unit or integration"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Ok "quick suite OK"
    }

    "unit" {
        Write-Section "Solo unit tests"
        python -m pytest $VFlag -m "unit"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Ok "unit suite OK"
    }

    "integration" {
        Write-Section "Solo integration tests"
        python -m pytest $VFlag -m "integration"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Ok "integration suite OK"
    }

    "e2e" {
        Write-Section "Tests E2E"
        python -m pytest $VFlag -m "e2e"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Ok "e2e suite OK"
    }

    "coverage" {
        Write-Section "Suite completa con coverage"
        python -m pytest $VFlag --cov --cov-report=term-missing --cov-report=html
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Ok "coverage report -> htmlcov/index.html"
    }

    "all" {
        # Suite completa (cov) + smoke E2E real
        Write-Section "FASE 1/2: pytest con coverage"
        python -m pytest $VFlag --cov --cov-report=term-missing --cov-report=html
        if ($LASTEXITCODE -ne 0) { Write-Fail "pytest fallo"; exit $LASTEXITCODE }
        Write-Ok "coverage report -> htmlcov/index.html"

        Write-Section "FASE 2/2: verify_signals_flow contra DB real"
        python scripts/signals/verify_signals_flow.py --cleanup
        if ($LASTEXITCODE -ne 0) { Write-Fail "verify_signals_flow fallo"; exit $LASTEXITCODE }
        Write-Ok "flow E2E verde"
    }
}

Write-Host ""
Write-Host "Todo OK" -ForegroundColor Green
exit 0
