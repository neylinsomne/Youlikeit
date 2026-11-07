# run_production.ps1 — runner del dominio Production.
#
# Owned by: docs/agents/PRODUCTION_AGENT.md
# Scope: pytest tests/production/ + smoke rotator sin render real

[CmdletBinding()]
param(
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

Section "FASE 1/2: pytest tests/production/"
python -m pytest $VFlag tests/production/
if ($LASTEXITCODE -ne 0) { Fail "pytest production fallo"; exit $LASTEXITCODE }
Ok "tests/production/ verde"

Section "FASE 2/2: smoke rotator (en seco, sin render)"
python -c @"
import sys, logging
sys.path.insert(0, 'src')
# Smoke offline y determinista: el rotator llama a trending_anime (red real,
# AniList/Jikan). Bloqueamos red + silenciamos WARNING para no depender de
# rate limits externos ni ensuciar stderr (PowerShell lo trata como error).
import requests
def _b(*a, **k):
    raise RuntimeError('offline smoke')
requests.get = requests.post = _b
requests.Session.get = requests.Session.post = _b
logging.disable(logging.WARNING)
from apps.production.content_rotator import ContentRotator, CATALOG
r = ContentRotator()
ok = 0
for p in ['deep_mind', 'pop_oracle', 'latam']:
    pick = r.pick_next(p, consume_briefs=False)
    if pick:
        print(f'  [OK] {p:12s} -> {pick[\"slug\"]:25s} score={pick[\"score\"]}')
        ok += 1
    else:
        print(f'  [FAIL] {p} sin pick (CATALOG vacio para esa persona?)')
print(f'CATALOG size: {len(CATALOG)} slugs')
sys.exit(0 if ok == 3 else 1)
"@
if ($LASTEXITCODE -ne 0) { Fail "smoke rotator fallo"; exit $LASTEXITCODE }
Ok "rotator pick para 3 personas"

Write-Host ""
Write-Host "Production domain OK" -ForegroundColor Green
exit 0
