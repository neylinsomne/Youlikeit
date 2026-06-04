param(
    [Parameter(Mandatory = $true)]
    [string]$Exercise,
    [string]$Query = "python automation",
    [string]$Url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    [string]$ChannelId = "UC_x5XG1OV2P6uZZ5FSM9Ttw"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $RepoRoot

$cmd = "python scripts/legacy/main.py $Exercise --query `"$Query`" --url `"$Url`" --channel-id `"$ChannelId`""
docker compose exec ytlab bash -lc $cmd
