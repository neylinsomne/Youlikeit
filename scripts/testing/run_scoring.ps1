# run_scoring.ps1 — runner del dominio Scoring.
#
# Owned by: docs/agents/SCORING_AGENT.md
# Scope: pytest tests/scoring/ + batch score sobre outputs/produce si existen

[CmdletBinding()]
param(
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

function Section($t) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}
function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Fail($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Skip($m) { Write-Host "  [SKIP] $m" -ForegroundColor Yellow }

$ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $ROOT

$VFlag = if ($Verbose) { "-vv" } else { "-q" }

Section "FASE 1/2: pytest tests/scoring/"
python -m pytest $VFlag tests/scoring/
if ($LASTEXITCODE -ne 0) { Fail "pytest scoring fallo"; exit $LASTEXITCODE }
Ok "tests/scoring/ verde"

Section "FASE 2/2: batch score_hooks sobre outputs/produce/"
$produce = Join-Path $ROOT "outputs/produce"
if (Test-Path $produce) {
    python scripts/scoring/score_hooks.py --csv out/hook_scores.csv
    if ($LASTEXITCODE -ne 0) { Fail "score_hooks fallo"; exit $LASTEXITCODE }
    Ok "scores escritos a out/hook_scores.csv"
} else {
    Skip "outputs/produce/ no existe — saltando batch score"
}

Write-Host ""
Write-Host "Scoring domain OK" -ForegroundColor Green
exit 0
