<#
.SYNOPSIS
  Creates (or removes) the "YouLikeIt Studio" shortcut on the Desktop and in the Start menu.

.DESCRIPTION
  The shortcut runs `studio.ps1 -App`: API + front start hidden on 127.0.0.1 and the studio
  opens in its own Edge window (no address bar). Closing that window stops everything.
  Only this shortcut uses -ExecutionPolicy Bypass; the machine policy is not changed.
  From the Start menu entry you can pin it to the taskbar (right click > Pin to taskbar).

.EXAMPLE
  .\scripts\ops\install-studio-shortcut.ps1           # create / update
  .\scripts\ops\install-studio-shortcut.ps1 -Remove   # remove both shortcuts
#>
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Studio   = Join-Path $RepoRoot 'scripts\ops\studio.ps1'
$Icon     = Join-Path $RepoRoot 'scripts\ops\assets\youlikeit-studio.ico'
$PwshExe  = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Name     = 'YouLikeIt Studio.lnk'
$Folders  = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))

$shell = New-Object -ComObject WScript.Shell
foreach ($dir in $Folders) {
    $path = Join-Path $dir $Name
    if ($Remove) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force; Write-Host "removed  $path" }
        continue
    }
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath       = $PwshExe
    $lnk.Arguments        = ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -App' -f $Studio)
    $lnk.WorkingDirectory = $RepoRoot
    $lnk.IconLocation     = ('{0},0' -f $Icon)
    $lnk.WindowStyle      = 7               # minimized: no console flash in the middle of the screen
    $lnk.Description      = 'YouLikeIt Studio (local, 127.0.0.1)'
    $lnk.Save()
    Write-Host "created  $path"
}
