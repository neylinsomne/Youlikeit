# run_all.ps1 — Audit completo por dominios.
#
# Owned by: docs/agents/QA_AGENT.md
# Ejecuta: signals → production → scoring → E2E + coverage
# Para auditorías más cortas usar run_tests.ps1 -Mode quick

[CmdletBinding()]
param(
    [switch]$WithCoverage,
    [switch]$WithLLM,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

function Section($t) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Magenta
    Write-Host "  $t" -ForegroundColor Magenta
    Write-Host ("=" * 70) -ForegroundColor Magenta
}
function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Fail($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }

$ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $ROOT

$results = @{}
$totalStart = Get-Date

# ── Dominio: Signals ───────────────────────────────────────────────
Section "DOMINIO 1/3: SIGNALS"
$args = @()
if ($Verbose) { $args += "-Verbose" }
if ($WithLLM) { $args += "-WithLLM" }
& "$PSScriptRoot\run_signals.ps1" @args
$results["signals"] = $LASTEXITCODE
if ($LASTEXITCODE -ne 0) { Fail "signals fallo" } else { Ok "signals OK" }

# ── Dominio: Production ────────────────────────────────────────────
Section "DOMINIO 2/3: PRODUCTION"
& "$PSScriptRoot\run_production.ps1" @args
$results["production"] = $LASTEXITCODE
if ($LASTEXITCODE -ne 0) { Fail "production fallo" } else { Ok "production OK" }

# ── Dominio: Scoring ───────────────────────────────────────────────
Section "DOMINIO 3/3: SCORING"
& "$PSScriptRoot\run_scoring.ps1" @args
$results["scoring"] = $LASTEXITCODE
if ($LASTEXITCODE -ne 0) { Fail "scoring fallo" } else { Ok "scoring OK" }

# ── Suite completa + coverage opcional ────────────────────────────
if ($WithCoverage) {
    Section "BONUS: suite completa con coverage HTML"
    python -m pytest --cov --cov-report=term-missing --cov-report=html
    $results["coverage"] = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) { Fail "coverage fallo" } else { Ok "htmlcov/index.html generado" }
}

# ── Resumen final ─────────────────────────────────────────────────
$totalSeconds = ((Get-Date) - $totalStart).TotalSeconds
Section "RESUMEN AUDIT COMPLETO"
foreach ($k in $results.Keys) {
    $exit = $results[$k]
    $mark = if ($exit -eq 0) { "[OK]  " } else { "[FAIL]" }
    $color = if ($exit -eq 0) { "Green" } else { "Red" }
    Write-Host "  $mark $($k.PadRight(15)) exit=$exit" -ForegroundColor $color
}
Write-Host ""
Write-Host ("  Tiempo total: {0:N1}s" -f $totalSeconds) -ForegroundColor Cyan

$failed = $results.Values | Where-Object { $_ -ne 0 }
if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "  AUDIT FALLIDO: $($failed.Count) dominios rotos" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "  AUDIT COMPLETO VERDE" -ForegroundColor Green
exit 0
