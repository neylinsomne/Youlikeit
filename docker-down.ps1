$ErrorActionPreference = "Stop"
Set-Location "D:\Youlikeit"

docker compose down
Write-Host "Servicios detenidos" -ForegroundColor Cyan
