$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py -3"
} else {
    throw "No se encontro Python ni py launcher en PATH."
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creando entorno virtual..." -ForegroundColor Cyan
    Invoke-Expression "$pythonCmd -m venv .venv"
}

Write-Host "Activando entorno virtual..." -ForegroundColor Cyan
. .\.venv\Scripts\Activate.ps1

Write-Host "Actualizando pip..." -ForegroundColor Cyan
python -m pip install --upgrade pip

Write-Host "Instalando dependencias..." -ForegroundColor Cyan
pip install -r requirements.txt

Write-Host "Instalando navegador Chromium para Playwright..." -ForegroundColor Cyan
python -m playwright install chromium

Write-Host "Listo. Ejecuta: python src\\main.py --list" -ForegroundColor Green
