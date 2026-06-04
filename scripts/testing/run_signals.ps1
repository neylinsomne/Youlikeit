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

$ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $ROOT

$VFlag = if ($Verbose) { "-vv" } else { "-q" }

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
    python scripts/signals/briefs_dashboard.py --validate --no-scraper --no-briefs --no-unresolved
    if ($LASTEXITCODE -ne 0) { Fail "validation fallo"; exit $LASTEXITCODE }
    Ok "invariantes hard pasan"
}

Write-Host ""
Write-Host "Signals domain OK" -ForegroundColor Green
exit 0
