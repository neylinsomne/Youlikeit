$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

docker compose up -d ytlab

docker compose exec ytlab bash -lc "pip install --upgrade pip && pip install -r requirements.txt && python -m playwright install chromium"

Write-Host "Entorno Docker listo." -ForegroundColor Green
Write-Host "Prueba: docker compose exec ytlab python scripts/legacy/main.py --list" -ForegroundColor Cyan
