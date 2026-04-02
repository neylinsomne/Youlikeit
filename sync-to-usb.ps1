# Sincroniza outputs del pipeline a la USB E:
# Ejecutar después de cada corrida o como tarea programada
#
# Uso: .\sync-to-usb.ps1

$Source = Join-Path $PSScriptRoot "outputs"
$Dest = "E:\youlikeit-outputs"

if (-not (Test-Path "E:\")) {
    Write-Host "ERROR: USB E: no esta conectada" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

# Robocopy: copia solo archivos nuevos/modificados, mantiene estructura
robocopy $Source $Dest /MIR /XO /NFL /NDL /NJH /NJS /NC /NS

$size = (Get-ChildItem $Dest -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "Sincronizado: $Source -> $Dest ($([math]::Round($size, 1)) MB)" -ForegroundColor Green
