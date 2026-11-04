<#
.SYNOPSIS
  Local production studio: API (ylk studio) + front (Vite), both on 127.0.0.1 only.

.DESCRIPTION
  1. Checks prerequisites: ylk (pip install -e .), node/npm, ffmpeg, STUDIO_TOKEN in .env,
     free ports.
  2. Starts the API (ylk studio -> 127.0.0.1:8001, or STUDIO_PORT) and the front
     (npm run dev -> 127.0.0.1:5180) as hidden background processes.
     Logs and the PID state file live in %TEMP%\youlikeit-studio (outside the repo).
  3. Waits until both listen and opens http://127.0.0.1:5180.
  STUDIO_TOKEN is read from the root .env and is never printed.
  Contract: docs/architecture/STUDIO_API.md

.EXAMPLE
  .\scripts\ops\studio.ps1              # start and open the browser
  .\scripts\ops\studio.ps1 -Check       # only check prerequisites
  .\scripts\ops\studio.ps1 -NoBrowser   # start without opening the browser
  .\scripts\ops\studio.ps1 -Stop        # stop API + front
#>

param(
    [switch]$Stop,
    [switch]$Check,
    [switch]$NoBrowser,
    [int]$TimeoutSec = 60
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $RepoRoot

$StudioHost = '127.0.0.1'
$FrontPort  = 5180
$FrontDir   = Join-Path $RepoRoot 'frontend-react'
$EnvFile    = Join-Path $RepoRoot '.env'
$StateDir   = Join-Path $env:TEMP 'youlikeit-studio'
$StateFile  = Join-Path $StateDir 'state.json'
$Ylk        = $null

function Show-Step([string]$Text) { Write-Host "[studio] $Text" -ForegroundColor Cyan }
function Show-Ok([string]$Text)   { Write-Host "  OK    $Text" -ForegroundColor Green }
function Show-Info([string]$Text) { Write-Host "  INFO  $Text" -ForegroundColor Gray }
function Show-Warn([string]$Text) { Write-Host "  WARN  $Text" -ForegroundColor Yellow }
function Show-Fail([string]$Text) { Write-Host "  FAIL  $Text" -ForegroundColor Red }

# Native tools write warnings to stderr (npm, typer, taskkill). Under "Stop", PS 5.1 can turn
# those lines into terminating errors when the host redirects stderr, so relax it here.
function Invoke-Native([scriptblock]$Block) {
    $ErrorActionPreference = 'Continue'
    & $Block
}

function Get-StartStamp($Proc) {
    try { return $Proc.StartTime.ToUniversalTime().ToString('o') } catch { return '' }
}

function Test-Exited($Proc) {
    try { return $Proc.HasExited } catch { return $true }
}

function Show-LogTail([string[]]$Logs) {
    foreach ($log in $Logs) {
        if (-not (Test-Path -LiteralPath $log)) { continue }
        try {
            $lines = @(Get-Content -LiteralPath $log -Tail 15 -ErrorAction Stop)
        } catch {
            Show-Info "log not readable yet: $log"
            continue
        }
        if ($lines.Count -gt 0) {
            Show-Info "--- $log"
            $lines | ForEach-Object { Write-Host "        $_" }
        }
    }
}

# Value of NAME in a dotenv file (last definition wins, like python-dotenv). Never printed.
function Get-DotEnvValue {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $value = $null
    $pattern = '^\s*(?:export\s+)?' + [regex]::Escape($Name) + '\s*=\s*(.*)$'
    foreach ($line in (Get-Content -LiteralPath $Path -Encoding UTF8)) {
        if ($line -match $pattern) {
            $v = $Matches[1].Trim()
            if ($v -match '^"(.*)"$' -or $v -match "^'(.*)'$") { $v = $Matches[1] }
            else { $v = ($v -replace '\s+#.*$', '').Trim() }
            $value = $v
        }
    }
    return $value
}

function Get-Setting([string]$Name) {
    $v = Get-DotEnvValue -Path $EnvFile -Name $Name
    if (-not $v) { $v = [Environment]::GetEnvironmentVariable($Name, 'Process') }
    return $v
}

function Get-PortOwner([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return $null
}

function Test-Port([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $client.BeginConnect($StudioHost, $Port, $null, $null)
        if (-not $ar.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($ar)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Read-State {
    if (-not (Test-Path -LiteralPath $StateFile)) { return $null }
    try { return (Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json) } catch { return $null }
}

# The tracked process, only if the PID still belongs to the process we started
# (same start time), so a reused PID is never killed by mistake.
function Get-TrackedProcess($Entry) {
    if (-not $Entry) { return $null }
    $p = Get-Process -Id ([int]$Entry.pid) -ErrorAction SilentlyContinue
    if (-not $p) { return $null }
    $stamp = Get-StartStamp $p
    if (-not $stamp -or $stamp -ne $Entry.started) { return $null }
    return $p
}

function Get-ApiPort {
    $raw = Get-Setting 'STUDIO_PORT'
    $port = 0
    if ($raw -and [int]::TryParse($raw, [ref]$port) -and $port -gt 0) { return $port }
    return 8001
}

function Stop-Studio {
    $state = Read-State
    if (-not $state) {
        Show-Step 'Studio is not running (no state file).'
    } else {
        Show-Step 'Stopping studio'
        foreach ($name in @('api', 'front')) {
            $p = Get-TrackedProcess $state.$name
            if ($p) {
                # /T stops the whole tree (ylk.exe -> python, cmd -> npm -> node).
                $procId = $p.Id
                Invoke-Native { & taskkill.exe /PID $procId /T /F 2>&1 | Out-Null }
                Show-Ok "$name stopped (pid $($p.Id))"
            } else {
                Show-Info "$name was not running"
            }
        }
        Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    }
    foreach ($port in @((Get-ApiPort), $FrontPort)) {
        $owner = Get-PortOwner $port
        if ($owner) { Show-Warn "port $port is still in use by pid $owner (not started by this script)" }
    }
}

function Test-Prerequisites([int]$ApiPort) {
    $ok = $true
    Show-Step 'Checking prerequisites'

    # Python + ylk (prefers the repo .venv if there is one)
    $venvYlk = Join-Path $RepoRoot '.venv\Scripts\ylk.exe'
    $cmd = Get-Command ylk -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $venvYlk) { $script:Ylk = $venvYlk }
    elseif ($cmd) { $script:Ylk = $cmd.Source }
    if (-not $script:Ylk) {
        Show-Fail 'ylk not found. From the repo root run: pip install -e .'
        $ok = $false
    } else {
        $ylkExe = $script:Ylk
        $help = @(Invoke-Native { & $ylkExe studio --help 2>&1 })
        if ($LASTEXITCODE -eq 0) {
            Show-Ok "ylk studio: $ylkExe"
        } else {
            Show-Fail "'ylk studio' is not available ($ylkExe). Update the repo and run: pip install -e ."
            $help | Select-Object -Last 6 | ForEach-Object { Write-Host "        $_" }
            $ok = $false
        }
    }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Show-Warn 'python not found in PATH' }

    # Node + npm
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node -and (Get-Command npm -ErrorAction SilentlyContinue)) { Show-Ok "node: $($node.Source)" }
    else { Show-Fail 'node/npm not found. Install Node.js 20.19+ or 22.12+ (https://nodejs.org)'; $ok = $false }
    if (-not (Test-Path -LiteralPath (Join-Path $FrontDir 'node_modules'))) {
        Show-Info 'frontend-react has no node_modules: npm install will run on start'
    }

    # ffmpeg (previews and render; browsing and review work without it)
    $ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($ff) { Show-Ok "ffmpeg: $($ff.Source)" }
    else { Show-Warn 'ffmpeg not found in PATH: previews and render will fail (winget install Gyan.FFmpeg)' }

    # STUDIO_TOKEN (value is never printed)
    $token = Get-Setting 'STUDIO_TOKEN'
    if (-not $token) {
        Show-Fail 'STUDIO_TOKEN is missing in .env. Generate one with:'
        Write-Host '          python -c "import secrets;print(secrets.token_urlsafe(32))"'
        Write-Host '        and add the line STUDIO_TOKEN=<value> to .env (do not share it).'
        $ok = $false
    } elseif ($token.Length -lt 32) {
        Show-Warn 'STUDIO_TOKEN is shorter than 32 characters: consider regenerating it'
    } else {
        Show-Ok 'STUDIO_TOKEN present (value not shown)'
    }

    # TikTok bridge (optional: only needed to publish to TikTok)
    if ((Get-Setting 'STUDIO_API_KEY') -and (Get-Setting 'WEB_BASE_URL')) {
        Show-Ok 'TikTok bridge configured (WEB_BASE_URL + STUDIO_API_KEY)'
    } else {
        Show-Info 'TikTok publishing needs WEB_BASE_URL and STUDIO_API_KEY in .env (optional)'
    }

    # Ports
    foreach ($port in @($ApiPort, $FrontPort)) {
        $owner = Get-PortOwner $port
        if ($owner) {
            $pname = (Get-Process -Id $owner -ErrorAction SilentlyContinue).ProcessName
            Show-Fail "port $port is in use by pid $owner ($pname). Stop it first (old Docker yt-api? docker compose down)"
            $ok = $false
        }
    }
    return $ok
}

function Wait-Ready($Proc, [int]$Port) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) { return $true }
        if (Test-Exited $Proc) { return $false }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# Warn if a port ended up listening on every interface instead of 127.0.0.1.
function Test-LoopbackOnly([string]$Name, [int]$Port) {
    $addrs = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { $_.LocalAddress })
    $open = @($addrs | Where-Object { $_ -eq '0.0.0.0' -or $_ -eq '::' })
    if ($open.Count -gt 0) {
        Show-Warn "$Name listens on all interfaces ($($open -join ', ')): it must bind to 127.0.0.1"
    }
}

function Start-Studio([int]$ApiPort) {
    $apiUrl = 'http://{0}:{1}' -f $StudioHost, $ApiPort
    $frontUrl = 'http://{0}:{1}' -f $StudioHost, $FrontPort

    if (-not (Test-Path -LiteralPath (Join-Path $FrontDir 'node_modules'))) {
        Show-Step 'Installing front dependencies (npm install, first run only)'
        Push-Location $FrontDir
        try {
            Invoke-Native { & $env:ComSpec /c npm install }
            if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
        } finally {
            Pop-Location
        }
    }

    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $apiLogs = @((Join-Path $StateDir 'api.err.log'), (Join-Path $StateDir 'api.log'))
    $frontLogs = @((Join-Path $StateDir 'front.err.log'), (Join-Path $StateDir 'front.log'))

    # Child-only environment: restored afterwards so this session is left untouched.
    $childEnv = @{
        'PYTHONUNBUFFERED' = '1'
        'PYTHONIOENCODING' = 'utf-8'
        'STUDIO_TOKEN'     = (Get-Setting 'STUDIO_TOKEN')
        'STUDIO_PORT'      = [string]$ApiPort
    }
    $saved = @{}
    foreach ($k in $childEnv.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k, 'Process') }
    try {
        foreach ($k in $childEnv.Keys) { [Environment]::SetEnvironmentVariable($k, $childEnv[$k], 'Process') }

        Show-Step "Starting API: ylk studio -> $apiUrl"
        $apiProc = Start-Process -FilePath $script:Ylk -ArgumentList 'studio' -WorkingDirectory $RepoRoot `
            -RedirectStandardError $apiLogs[0] -RedirectStandardOutput $apiLogs[1] -WindowStyle Hidden -PassThru

        Show-Step "Starting front: npm run dev -> $frontUrl"
        $frontArgs = '/c npm run dev -- --host {0} --port {1} --strictPort' -f $StudioHost, $FrontPort
        $frontProc = Start-Process -FilePath $env:ComSpec -ArgumentList $frontArgs -WorkingDirectory $FrontDir `
            -RedirectStandardError $frontLogs[0] -RedirectStandardOutput $frontLogs[1] -WindowStyle Hidden -PassThru
    } finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], 'Process') }
    }

    $state = [ordered]@{
        api        = [ordered]@{ pid = $apiProc.Id; started = (Get-StartStamp $apiProc) }
        front      = [ordered]@{ pid = $frontProc.Id; started = (Get-StartStamp $frontProc) }
        api_port   = $ApiPort
        front_port = $FrontPort
        logs       = $StateDir
    }
    $state | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $StateFile -Encoding ASCII

    Show-Step "Waiting up to $TimeoutSec s for both to listen"
    $failed = $null
    if (-not (Wait-Ready $apiProc $ApiPort)) { $failed = @('API', $ApiPort, $apiLogs) }
    elseif (-not (Wait-Ready $frontProc $FrontPort)) { $failed = @('Front', $FrontPort, $frontLogs) }
    if ($failed) {
        Show-Fail ('{0} did not start on port {1}. Stopping both.' -f $failed[0], $failed[1])
        Stop-Studio
        Show-LogTail $failed[2]
        exit 1
    }
    Test-LoopbackOnly 'API' $ApiPort
    Test-LoopbackOnly 'Front' $FrontPort

    Write-Host ''
    Show-Ok "API    $apiUrl  (pid $($apiProc.Id))"
    Show-Ok "Studio $frontUrl  (pid $($frontProc.Id))"
    Show-Info "Logs: $StateDir"
    Show-Info 'Stop with: .\scripts\ops\studio.ps1 -Stop'
    if (-not $NoBrowser) { Start-Process $frontUrl }
}

# -- main ------------------------------------------------------------------
if ($Stop) {
    Stop-Studio
    exit 0
}

$running = Read-State
if ($running -and ((Get-TrackedProcess $running.api) -or (Get-TrackedProcess $running.front))) {
    $url = 'http://{0}:{1}' -f $StudioHost, $FrontPort
    Show-Step "Studio is already running ($url). Use -Stop to stop it."
    if (-not $Check -and -not $NoBrowser) { Start-Process $url }
    exit 0
}
if ($running) { Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue }

$apiPort = Get-ApiPort
if (-not (Test-Prerequisites $apiPort)) {
    Show-Step 'Fix the FAIL items above and run again.'
    exit 1
}
if ($Check) {
    Show-Step 'All prerequisites OK.'
    exit 0
}
Start-Studio $apiPort
