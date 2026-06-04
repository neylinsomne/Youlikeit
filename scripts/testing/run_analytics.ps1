# run_analytics.ps1 — runner del dominio Analytics (Plausible).
#
# Owned by: docs/agents/ANALYTICS_AGENT.md  (carpeta scripts/testing/ = QA Agent)
# Scope: pytest tests/analytics/ + smoke client (si PLAUSIBLE_API_KEY) + smoke bridge
#
# Uso:
#   .\scripts\testing\run_analytics.ps1
#   .\scripts\testing\run_analytics.ps1 -SkipSmoke   # solo pytest
#   .\scripts\testing\run_analytics.ps1 -Verbose

[CmdletBinding()]
param(
    [switch]$SkipSmoke,
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

Section "FASE 1/3: pytest tests/analytics/"
python -m pytest $VFlag tests/analytics/
if ($LASTEXITCODE -ne 0) { Fail "pytest analytics fallo"; exit $LASTEXITCODE }
Ok "tests/analytics/ verde"

if (-not $SkipSmoke) {
    Section "FASE 2/3: smoke Stats API (si PLAUSIBLE_API_KEY)"
    if ($env:PLAUSIBLE_API_KEY) {
        python scripts/analytics/fetch_plausible_stats.py --period 7d --json
        if ($LASTEXITCODE -ne 0) { Fail "fetch stats fallo (instancia caida?)"; exit $LASTEXITCODE }
        Ok "Stats API responde"
    } else {
        Write-Host "  [SKIP] PLAUSIBLE_API_KEY no set - smoke de API omitido" -ForegroundColor Yellow
    }

    Section "FASE 3/3: smoke bridge (pageview sintetico -> Signal internal)"
    # DB temporal aislada: NO contamina data/ ni el enum domain de prod.
    python -c @"
import sys, sqlite3
sys.path.insert(0, 'src')
from core.db import SCHEMA, _migrate_columns
from apps.analytics.internal_signals import signals_from_plausible
c = sqlite3.connect(':memory:'); c.row_factory = sqlite3.Row
c.executescript(SCHEMA); _migrate_columns(c)
c.execute(\"INSERT INTO plausible_pageviews (page, visitors, pageviews, bounce_rate, visit_duration, period_start, period_end) VALUES ('/dashboard.html', 42, 80, 40.0, 90.0, '2026-05-25', '2026-06-01')\")
c.commit()
sigs = signals_from_plausible(c, 'deep_mind')
assert sigs and sigs[0].domain == 'internal' and sigs[0].raw_score == 42.0, 'bridge roto'
print('  bridge OK:', sigs[0].title)
"@
    if ($LASTEXITCODE -ne 0) { Fail "smoke bridge fallo"; exit $LASTEXITCODE }
    Ok "bridge pageview -> Signal(internal) verde"
}

Write-Host ""
Write-Host "Analytics domain OK" -ForegroundColor Green
exit 0
