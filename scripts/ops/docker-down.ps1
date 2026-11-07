$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $RepoRoot

docker compose down
Write-Host "Servicios detenidos" -ForegroundColor Cyan
