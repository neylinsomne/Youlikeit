# YouLikeIt - Windows Scheduled Tasks Setup
# Run as Administrator: powershell -ExecutionPolicy Bypass -File setup-scheduled-tasks.ps1

$ProjectDir = "D:\Youlikeit\youtube-automatizacion-ejercicios"
$LogDir = "$ProjectDir\outputs\logs\scheduler"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "=== YouLikeIt Scheduled Tasks Setup ===" -ForegroundColor Cyan

# --- Task 1: Start Docker Desktop on Windows startup ---
$dockerPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
if (Test-Path $dockerPath) {
    $action = New-ScheduledTaskAction -Execute $dockerPath
    $trigger = New-ScheduledTaskTrigger -AtLogon
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

    Register-ScheduledTask -TaskName "YouLikeIt-DockerStart" `
        -Action $action -Trigger $trigger -Settings $settings `
        -Description "Start Docker Desktop for YouLikeIt pipeline" `
        -Force

    Write-Host "[OK] Docker Desktop auto-start on login" -ForegroundColor Green
} else {
    Write-Host "[SKIP] Docker Desktop not found at $dockerPath" -ForegroundColor Yellow
}

# --- Task 2: Daily content pipeline at 1am Colombia (6am UTC) ---
# Skips days 15-18
$pipelineScript = @"
`$ErrorActionPreference = 'Continue'
`$logFile = "$LogDir\pipeline_`$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
`$day = (Get-Date).Day

# Skip days 15-18
if (`$day -ge 15 -and `$day -le 18) {
    "SKIPPED: Day `$day is in exclusion range 15-18" | Out-File `$logFile
    exit 0
}

# Wait for Docker to be ready
`$maxWait = 120
`$waited = 0
while (-not (docker info 2>`$null)) {
    Start-Sleep -Seconds 5
    `$waited += 5
    if (`$waited -ge `$maxWait) {
        "ERROR: Docker not ready after `${maxWait}s" | Out-File `$logFile
        exit 1
    }
}

# Start containers if not running
Set-Location "$ProjectDir"
docker compose up -d ytlab api fish-speech 2>&1 | Out-File `$logFile -Append
Start-Sleep -Seconds 30

# Run manga pipeline
"=== MANGA PIPELINE START: `$(Get-Date) ===" | Out-File `$logFile -Append
docker compose exec -T ytlab bash -c 'cd /workspace/src && python main.py ex36 --media-type all --max-movies 10' 2>&1 | Out-File `$logFile -Append
docker compose exec -T ytlab bash -c 'cd /workspace/src && python main.py ex37 --provider auto --batch-size 30' 2>&1 | Out-File `$logFile -Append
docker compose exec -T ytlab bash -c 'cd /workspace/src && python main.py ex08 --query "anime manga trending" --country-code CO' 2>&1 | Out-File `$logFile -Append

# Run learning cycle (weekends only)
`$dow = (Get-Date).DayOfWeek
if (`$dow -eq 'Saturday' -or `$dow -eq 'Sunday') {
    "=== LEARNING CYCLE START: `$(Get-Date) ===" | Out-File `$logFile -Append
    docker compose exec -T ytlab bash -c 'cd /workspace/src && python main.py ex31 --batch-size 50' 2>&1 | Out-File `$logFile -Append
    docker compose exec -T ytlab bash -c 'cd /workspace/src && python main.py ex32' 2>&1 | Out-File `$logFile -Append
    docker compose exec -T ytlab bash -c 'cd /workspace/src && python main.py ex33 --plan-size 10' 2>&1 | Out-File `$logFile -Append
}

"=== PIPELINE DONE: `$(Get-Date) ===" | Out-File `$logFile -Append

# Cleanup old logs (keep 30 days)
Get-ChildItem "$LogDir\pipeline_*.log" | Where-Object { `$_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Force
"@

$pipelineScriptPath = "$ProjectDir\scripts\daily-pipeline.ps1"
$pipelineScript | Out-File -FilePath $pipelineScriptPath -Encoding UTF8

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$pipelineScriptPath`""

$trigger = New-ScheduledTaskTrigger -Daily -At "1:00AM"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName "YouLikeIt-DailyPipeline" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "YouLikeIt daily content pipeline (1am, skips 15-18)" `
    -Force

Write-Host "[OK] Daily pipeline at 1:00 AM (skips days 15-18)" -ForegroundColor Green

# --- Task 3: Analytics pull (daily at 8am, after YouTube processes data) ---
$analyticsScript = @"
`$ErrorActionPreference = 'Continue'
`$logFile = "$LogDir\analytics_`$(Get-Date -Format 'yyyyMMdd').log"

Set-Location "$ProjectDir"

# Wait for Docker
`$maxWait = 60
`$waited = 0
while (-not (docker info 2>`$null)) {
    Start-Sleep -Seconds 5
    `$waited += 5
    if (`$waited -ge `$maxWait) { exit 1 }
}

docker compose up -d ytlab 2>&1 | Out-File `$logFile -Append
Start-Sleep -Seconds 10

"=== ANALYTICS PULL: `$(Get-Date) ===" | Out-File `$logFile -Append
docker compose exec -T ytlab bash -c 'cd /workspace/src && python main.py ex19 2>/dev/null || true' 2>&1 | Out-File `$logFile -Append
docker compose exec -T ytlab bash -c 'cd /workspace/src && python main.py ex24 2>/dev/null || true' 2>&1 | Out-File `$logFile -Append

"=== DONE: `$(Get-Date) ===" | Out-File `$logFile -Append
"@

$analyticsScriptPath = "$ProjectDir\scripts\daily-analytics.ps1"
$analyticsScript | Out-File -FilePath $analyticsScriptPath -Encoding UTF8

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$analyticsScriptPath`""

$trigger = New-ScheduledTaskTrigger -Daily -At "8:00AM"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName "YouLikeIt-DailyAnalytics" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "YouLikeIt daily analytics pull from YouTube (8am)" `
    -Force

Write-Host "[OK] Daily analytics at 8:00 AM" -ForegroundColor Green

# --- Task 4: Trending songs cache refresh (daily at 6am) ---
$trendingScript = @"
`$ErrorActionPreference = 'Continue'
Set-Location "$ProjectDir"
`$maxWait = 60; `$waited = 0
while (-not (docker info 2>`$null)) { Start-Sleep 5; `$waited += 5; if (`$waited -ge `$maxWait) { exit 1 } }
docker compose up -d ytlab 2>&1 | Out-Null
Start-Sleep 10
docker compose exec -T ytlab bash -c 'cd /workspace/src && python -c "
from ytmusicapi import YTMusic
import sqlite3
yt = YTMusic()
charts = yt.get_charts(country=\"US\")
pid = charts[\"videos\"][0][\"playlistId\"]
try:
    pl = yt.get_playlist(pid, limit=25)
    songs = [(t.get(\"title\",\"\"), (t.get(\"artists\",[{}])[0].get(\"name\",\"\") if t.get(\"artists\") else \"\"), f\"https://music.youtube.com/watch?v={t.get(\"videoId\",\"\")}\", t.get(\"views\",\"\"), \"\", t.get(\"duration\",\"\")) for t in pl.get(\"tracks\",[])[:25]]
except:
    results = yt.search(\"trending songs 2026\", filter=\"songs\", limit=20)
    songs = [(r.get(\"title\",\"\"), (r.get(\"artists\",[{}])[0].get(\"name\",\"\") if r.get(\"artists\") else \"\"), f\"https://music.youtube.com/watch?v={r.get(\"videoId\",\"\")}\", r.get(\"views\",\"\"), \"\", r.get(\"duration\",\"\")) for r in results]
conn = sqlite3.connect(\"/workspace/data/shorts_pipeline.db\")
conn.execute(\"DELETE FROM trending_songs\")
for s in songs: conn.execute(\"INSERT INTO trending_songs (title,artist,youtube_url,views,thumbnail,duration) VALUES (?,?,?,?,?,?)\", s)
conn.commit()
print(f\"Cached {len(songs)} songs\")
"' 2>&1 | Out-Null
"@

$trendingScriptPath = "$ProjectDir\scripts\daily-trending.ps1"
$trendingScript | Out-File -FilePath $trendingScriptPath -Encoding UTF8

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$trendingScriptPath`""

$trigger = New-ScheduledTaskTrigger -Daily -At "6:00AM"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "YouLikeIt-TrendingCache" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "YouLikeIt trending songs cache refresh (6am)" `
    -Force

Write-Host "[OK] Trending songs cache at 6:00 AM" -ForegroundColor Green

# --- Summary ---
Write-Host "`n=== Scheduled Tasks Created ===" -ForegroundColor Cyan
Write-Host "  1. Docker auto-start        : On login" -ForegroundColor White
Write-Host "  2. Content pipeline          : Daily 1:00 AM (skip 15-18)" -ForegroundColor White
Write-Host "  3. Analytics pull            : Daily 8:00 AM" -ForegroundColor White
Write-Host "  4. Trending songs cache      : Daily 6:00 AM" -ForegroundColor White
Write-Host "`nAll logs saved to: $LogDir" -ForegroundColor Gray
Write-Host "To remove: Get-ScheduledTask 'YouLikeIt-*' | Unregister-ScheduledTask" -ForegroundColor Gray
