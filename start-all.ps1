$ErrorActionPreference = "Stop"

$root = "D:\Youlikeit"
$stateDir = Join-Path $root ".orchestrator"
$stateFile = Join-Path $stateDir "processes.json"

if (-not (Test-Path $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir | Out-Null
}

$projects = @(
    @{
        Name = "promptfoo"
        Path = Join-Path $root "promptfoo"
        Command = "npm run dev"
        Requires = @("npm")
    },
    @{
        Name = "nanochat"
        Path = Join-Path $root "nanochat"
        Command = "python -m scripts.chat_web"
        Requires = @("python")
    },
    @{
        Name = "impeccable"
        Path = Join-Path $root "impeccable"
        Command = "bun run dev"
        Requires = @("bun")
    },
    @{
        Name = "heretic"
        Path = Join-Path $root "heretic"
        Command = "python -m heretic.main"
        Requires = @("python")
    },
    @{
        Name = "OpenViking"
        Path = Join-Path $root "OpenViking"
        Command = "openviking-server"
        Requires = @("openviking-server")
    }
)

$started = @()

foreach ($project in $projects) {
    if (-not (Test-Path $project.Path)) {
        Write-Host "[SKIP] $($project.Name): carpeta no encontrada ($($project.Path))" -ForegroundColor Yellow
        continue
    }

    $missing = @()
    foreach ($tool in $project.Requires) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            $missing += $tool
        }
    }

    if ($missing.Count -gt 0) {
        $missingText = $missing -join ", "
        Write-Host "[SKIP] $($project.Name): faltan herramientas ($missingText)" -ForegroundColor Yellow
        continue
    }

    $shellCommand = "Set-Location '$($project.Path)'; $($project.Command)"
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $shellCommand) -PassThru

    $started += [PSCustomObject]@{
        name = $project.Name
        path = $project.Path
        command = $project.Command
        pid = $proc.Id
        startedAt = (Get-Date).ToString("o")
    }

    Write-Host "[OK] $($project.Name): PID $($proc.Id)" -ForegroundColor Green
}

$started | ConvertTo-Json -Depth 5 | Set-Content -Path $stateFile -Encoding UTF8
Write-Host "Estado guardado en $stateFile" -ForegroundColor Cyan
