param(
    [string]$TaskName = "YouTubeShortsFlowEvery3Days",
    [string]$StartTime = "09:00",
    [string]$Query = "epic villain moment",
    [string]$CountryCode = "CO"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$scriptPath = Join-Path $PSScriptRoot "run-content-flow.ps1"
if (-not (Test-Path $scriptPath)) {
    throw "Script not found: $scriptPath"
}

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Query `"$Query`" -CountryCode $CountryCode -UseDocker"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
$trigger = New-ScheduledTaskTrigger -Daily -DaysInterval 3 -At $StartTime

# Run as current user without requiring stored password.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Scheduled task created: $TaskName"
Write-Host "Runs every 3 days at $StartTime"
Write-Host "Next step: validate with -> Get-ScheduledTask -TaskName $TaskName"
