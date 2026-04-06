$ErrorActionPreference = "Stop"
Set-Location "D:\Youlikeit"

docker compose up -d --build
Write-Host "Servicios levantados. Estado:" -ForegroundColor Cyan
docker compose ps
