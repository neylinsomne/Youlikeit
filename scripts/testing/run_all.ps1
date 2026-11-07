# run_all.ps1 — Audit completo por dominios.
#
# Owned by: docs/agents/QA_AGENT.md
# Ejecuta: signals → production → scoring → analytics → E2E conjunto + coverage
# Para auditorías más cortas usar run_tests.ps1 -Mode quick

[CmdletBinding()]
param(
    [switch]$WithCoverage,
    [switch]$WithLLM,
    [switch]$Detailed
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

# Superficie de parametros por runner: solo signals acepta -WithLLM; el resto
# solo -Detailed. Usamos HASHTABLE splatting (liga por nombre, sin la
# ambiguedad del array-splat con switches). Cada grupo su propio splat.
$detailSplat = @{}
if ($Detailed) { $detailSplat["Detailed"] = $true }
$signalSplat = @{}
if ($Detailed) { $signalSplat["Detailed"] = $true }
if ($WithLLM)  { $signalSplat["WithLLM"]  = $true }

# ── Dominio: Signals ───────────────────────────────────────────────
Section "DOMINIO 1/4: SIGNALS"
& "$PSScriptRoot\run_signals.ps1" @signalSplat
$results["signals"] = $LASTEXITCODE
if ($LASTEXITCODE -ne 0) { Fail "signals fallo" } else { Ok "signals OK" }

# ── Dominio: Production ────────────────────────────────────────────
Section "DOMINIO 2/4: PRODUCTION"
& "$PSScriptRoot\run_production.ps1" @detailSplat
$results["production"] = $LASTEXITCODE
if ($LASTEXITCODE -ne 0) { Fail "production fallo" } else { Ok "production OK" }

# ── Dominio: Scoring ───────────────────────────────────────────────
Section "DOMINIO 3/4: SCORING"
& "$PSScriptRoot\run_scoring.ps1" @detailSplat
$results["scoring"] = $LASTEXITCODE
if ($LASTEXITCODE -ne 0) { Fail "scoring fallo" } else { Ok "scoring OK" }

# ── Dominio: Analytics ─────────────────────────────────────────────
Section "DOMINIO 4/4: ANALYTICS"
& "$PSScriptRoot\run_analytics.ps1" @detailSplat
$results["analytics"] = $LASTEXITCODE
if ($LASTEXITCODE -ne 0) { Fail "analytics fallo" } else { Ok "analytics OK" }

# ── E2E conjunto: TODO el pipeline con datos mock ──────────────────
Section "E2E CONJUNTO: verify_full_flow (5 dominios, offline)"
python scripts/testing/verify_full_flow.py
$results["e2e_full_flow"] = $LASTEXITCODE
if ($LASTEXITCODE -ne 0) { Fail "E2E conjunto fallo" } else { Ok "E2E conjunto VERDE" }

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
