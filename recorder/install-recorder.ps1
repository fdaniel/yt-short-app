<#
.SYNOPSIS
Installs the Loadout Recorder on the gaming PC.

.DESCRIPTION
Copies the recorder to %LOCALAPPDATA%\LoadoutRecorder, saves the OBS WebSocket
password encrypted for this Windows user, adds the recorder to the Startup
folder (hidden window) and starts it now. Running it again updates everything.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$installDir = Join-Path $env:LOCALAPPDATA 'LoadoutRecorder'
$settingsDir = Join-Path $env:APPDATA 'LoadoutRecorder'
$script = Join-Path $installDir 'loadout-recorder.ps1'
$startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'Loadout Recorder.lnk'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""

New-Item -ItemType Directory -Force -Path $installDir, $settingsDir | Out-Null
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($script) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Copy-Item (Join-Path $PSScriptRoot 'loadout-recorder.ps1') $script -Force
Unblock-File $script

$password = Read-Host 'Paste the OBS WebSocket password (OBS > Tools > WebSocket Server Settings > Show Connect Info)' -AsSecureString
@{ obs_password = ($password | ConvertFrom-SecureString) } | ConvertTo-Json |
    Set-Content (Join-Path $settingsDir 'settings.json')

$link = (New-Object -ComObject WScript.Shell).CreateShortcut($startup)
$link.TargetPath = $powershell
$link.Arguments = $arguments
$link.WindowStyle = 7
$link.Description = 'Loadout Recorder: records Steam games with OBS'
$link.Save()

Start-Process -FilePath $powershell -ArgumentList $arguments -WindowStyle Hidden
Write-Host ''
Write-Host 'Loadout Recorder is installed and running. It starts with Windows from now on.'
Write-Host "Recordings: $(Join-Path $env:USERPROFILE 'Loadout Recorder')"
Write-Host "Log: $(Join-Path $settingsDir 'recorder.log')"
