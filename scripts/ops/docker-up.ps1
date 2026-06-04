$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $RepoRoot

docker compose up -d --build
Write-Host "Servicios levantados. Estado:" -ForegroundColor Cyan
docker compose ps
