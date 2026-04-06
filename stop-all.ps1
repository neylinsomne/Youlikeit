$ErrorActionPreference = "Stop"

$root = "D:\Youlikeit"
$stateFile = Join-Path $root ".orchestrator\processes.json"

if (-not (Test-Path $stateFile)) {
    Write-Host "No hay estado de procesos en $stateFile" -ForegroundColor Yellow
    exit 0
}

$entries = Get-Content $stateFile -Raw | ConvertFrom-Json

foreach ($entry in $entries) {
    $proc = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        Write-Host "[INFO] $($entry.name): PID $($entry.pid) ya no existe" -ForegroundColor Yellow
        continue
    }

    Stop-Process -Id $entry.pid -Force
    Write-Host "[STOP] $($entry.name): PID $($entry.pid) detenido" -ForegroundColor Green
}

Remove-Item $stateFile -Force
Write-Host "Estado eliminado" -ForegroundColor Cyan
