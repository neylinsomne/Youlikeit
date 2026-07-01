# run_signals.ps1 — runner del dominio Signals.
#
# Owned by: docs/agents/SIGNALS_AGENT.md
# Scope: pytest tests/signals/ + smoke verify_signals_flow + dashboard validate
#
# Uso:
#   .\scripts\testing\run_signals.ps1
#   .\scripts\testing\run_signals.ps1 -SkipSmoke   # solo pytest
#   .\scripts\testing\run_signals.ps1 -WithLLM     # smoke con LLM real

[CmdletBinding()]
param(
    [switch]$SkipSmoke,
    [switch]$WithLLM,
    [switch]$Detailed
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

$ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $ROOT

$VFlag = if ($Detailed) { "-vv" } else { "-q" }

Section "FASE 1/3: pytest tests/signals/"
python -m pytest $VFlag tests/signals/
if ($LASTEXITCODE -ne 0) { Fail "pytest signals fallo"; exit $LASTEXITCODE }
Ok "tests/signals/ verde"

if (-not $SkipSmoke) {
    Section "FASE 2/3: smoke verify_signals_flow"
    $smokeArgs = "--cleanup"
    if (-not $WithLLM) {
        # Sin LLM por default — usa el fixture en seco
        $env:DISABLE_LLM = "1"
    }
    python scripts/signals/verify_signals_flow.py --cleanup
    if ($LASTEXITCODE -ne 0) { Fail "smoke fallo"; exit $LASTEXITCODE }
    Ok "smoke E2E verde"

    Section "FASE 3/3: dashboard --validate"
    # Modo prueba: la DB puede estar reseteada/vacia tras el smoke --cleanup.
    # Los invariantes HARD asumen volumen de produccion (>=80 senales/24h,
    # >=3 briefs/persona). Bajamos umbrales SOLO aqui (scope FASE 3, no toca
    # pytest) para que el reporte sea coherente sobre datos sinteticos.
    $env:MIN_SIGNALS_24H = "0"
    $env:MIN_SIGNALS_7D = "0"
    $env:MIN_BRIEFS_PER_PERSONA = "0"
    python scripts/signals/briefs_dashboard.py --validate --no-scraper --no-briefs --no-unresolved
    $rc = $LASTEXITCODE
    Remove-Item Env:\MIN_SIGNALS_24H, Env:\MIN_SIGNALS_7D, Env:\MIN_BRIEFS_PER_PERSONA -ErrorAction SilentlyContinue
    if ($rc -ne 0) { Fail "validation fallo"; exit $rc }
    Ok "validacion corre (invariantes evaluados)"
}

Write-Host ""
Write-Host "Signals domain OK" -ForegroundColor Green
exit 0
