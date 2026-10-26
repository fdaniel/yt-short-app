<#
.SYNOPSIS
Loadout Recorder: records your Steam games with OBS, hands-free.

.DESCRIPTION
Runs in the background on the gaming PC. While Steam runs a game it keeps OBS
recording into the work folder (it restarts OBS or the recording if either
stops). When the game closes it stops OBS and moves every file recorded during
that game into the ready folder, named after the game (for example
1492070_Sker-Ritual_2026-10-26_21-05-33.mp4), so the Loadout Daily app knows
which game it shows. Work and ready folders sit on the same drive, so a file
appears in the ready folder (which Syncthing shares) only when it is complete.

Talks to OBS through its built-in WebSocket server (protocol v5). The password
is read from the settings file, encrypted for this Windows user only.
#>
param(
    [string]$SteamKey = 'HKCU:\Software\Valve\Steam',
    [string]$SteamProcess = 'steam',
    [string]$ReadyFolder = (Join-Path $env:USERPROFILE 'Loadout Recorder'),
    [string]$WorkFolder = (Join-Path $env:LOCALAPPDATA 'LoadoutRecorder\recording'),
    [string]$ObsUrl = 'ws://127.0.0.1:4455',
    [string]$SettingsFile = (Join-Path $env:APPDATA 'LoadoutRecorder\settings.json'),
    [string]$ObsExe = (Join-Path $env:ProgramFiles 'obs-studio\bin\64bit\obs64.exe'),
    [int]$PollSeconds = 5,
    [int]$RetrySeconds = 60,
    [int]$GiveUpMinutes = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$LogFile = Join-Path (Split-Path $SettingsFile) 'recorder.log'
$ObsProcess = [IO.Path]::GetFileNameWithoutExtension($ObsExe)
$TimeoutMs = 10000

function Write-Log([string]$Message) {
    $line = '{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $Message
    New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null
    Add-Content -Path $LogFile -Value $line
}

function Get-ObsPassword {
    if (-not (Test-Path $SettingsFile)) { return '' }
    $saved = (Get-Content -Raw $SettingsFile | ConvertFrom-Json).obs_password
    if (-not $saved) { return '' }
    $secure = ConvertTo-SecureString $saved
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Get-Sha256Base64([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [Convert]::ToBase64String($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text))) }
    finally { $sha.Dispose() }
}

function Get-ObsAuth([string]$Password, $Challenge) {
    $secret = Get-Sha256Base64 ($Password + $Challenge.salt)
    return Get-Sha256Base64 ($secret + $Challenge.challenge)
}

function Send-Message($Socket, $Message) {
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Message | ConvertTo-Json -Depth 5 -Compress))
    $segment = New-Object ArraySegment[byte] -ArgumentList @(, $bytes)
    $sent = $Socket.SendAsync($segment, 'Text', $true, [Threading.CancellationToken]::None)
    if (-not $sent.Wait($TimeoutMs)) { throw 'OBS did not accept the message in time' }
}

function Receive-Message($Socket) {
    $buffer = New-Object byte[] 65536
    $stream = New-Object IO.MemoryStream
    do {
        $segment = New-Object ArraySegment[byte] -ArgumentList @(, $buffer)
        $read = $Socket.ReceiveAsync($segment, [Threading.CancellationToken]::None)
        if (-not $read.Wait($TimeoutMs)) { throw 'OBS did not answer in time' }
        if ($read.Result.MessageType -eq 'Close') { throw 'OBS closed the connection (wrong WebSocket password?)' }
        $stream.Write($buffer, 0, $read.Result.Count)
    } until ($read.Result.EndOfMessage)
    return [Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
}

function Connect-Obs {
    $socket = New-Object Net.WebSockets.ClientWebSocket
    if (-not $socket.ConnectAsync([Uri]$ObsUrl, [Threading.CancellationToken]::None).Wait($TimeoutMs)) {
        throw 'OBS is not answering'
    }
    $hello = Receive-Message $socket
    $identify = @{ rpcVersion = 1; eventSubscriptions = 0 }
    if ($hello.d.PSObject.Properties['authentication']) {
        $identify.authentication = Get-ObsAuth (Get-ObsPassword) $hello.d.authentication
    }
    Send-Message $socket @{ op = 1; d = $identify }
    $identified = Receive-Message $socket
    if ($identified.op -ne 2) { throw 'OBS refused the connection' }
    return $socket
}

function Invoke-Obs([string]$RequestType, [hashtable]$Data = @{}) {
    $socket = Connect-Obs
    try {
        $id = [guid]::NewGuid().ToString()
        Send-Message $socket @{ op = 6; d = @{ requestType = $RequestType; requestId = $id; requestData = $Data } }
        do { $reply = Receive-Message $socket } until ($reply.op -eq 7 -and $reply.d.requestId -eq $id)
        $status = $reply.d.requestStatus
        if (-not $status.result) {
            $why = if ($status.PSObject.Properties['comment']) { $status.comment } else { "code $($status.code)" }
            throw "OBS refused ${RequestType}: $why"
        }
        if ($reply.d.PSObject.Properties['responseData']) { return $reply.d.responseData }
    }
    finally {
        if ($socket.State -eq 'Open') {
            $socket.CloseAsync('NormalClosure', 'done', [Threading.CancellationToken]::None).Wait($TimeoutMs) | Out-Null
        }
        $socket.Dispose()
    }
}

function Test-ObsOpen { return [bool](Get-Process $ObsProcess -ErrorAction SilentlyContinue) }

function Start-ObsIfClosed {
    if ((Test-ObsOpen) -or -not (Test-Path $ObsExe)) { return }
    Write-Log 'Starting OBS'
    $flags = @('--minimize-to-tray', '--disable-shutdown-check')
    Start-Process -FilePath $ObsExe -WorkingDirectory (Split-Path $ObsExe) -ArgumentList $flags
    Start-Sleep -Seconds 15
}

function Get-RunningGame {
    # After a crash the registry can still name the last game; it only counts while Steam runs.
    if (-not (Get-Process $SteamProcess -ErrorAction SilentlyContinue)) { return 0 }
    $props = Get-ItemProperty -Path $SteamKey -ErrorAction SilentlyContinue
    if (-not $props -or -not $props.PSObject.Properties['RunningAppID']) { return 0 }
    return [int]$props.RunningAppID
}

function Get-GameName([int]$AppId) {
    $app = Get-ItemProperty -Path (Join-Path $SteamKey "Apps\$AppId") -ErrorAction SilentlyContinue
    if ($app -and $app.PSObject.Properties['Name'] -and $app.Name) { return [string]$app.Name }
    return "app-$AppId"
}

function Get-SafeName([string]$Name) {
    $safe = ($Name -replace '[^A-Za-z0-9]+', '-').Trim('-')
    if ($safe.Length -gt 60) { $safe = $safe.Substring(0, 60).Trim('-') }
    if (-not $safe) { return 'game' }
    return $safe
}

function Test-FileClosed([string]$Path) {
    try { [IO.File]::Open($Path, 'Open', 'Read', 'None').Dispose(); return $true }
    catch { return $false }
}

function Get-ReadyPath($Session, $File) {
    $base = '{0}_{1}_{2:yyyy-MM-dd_HH-mm-ss}' -f $Session.AppId, (Get-SafeName $Session.Name), $File.CreationTime
    $target = Join-Path $ReadyFolder ($base + $File.Extension)
    $copy = 2
    while (Test-Path -LiteralPath $target) {
        $target = Join-Path $ReadyFolder ('{0}-{1}{2}' -f $base, $copy, $File.Extension)
        $copy++
    }
    return $target
}

function New-Session([int]$AppId) {
    return @{ AppId = $AppId; Name = Get-GameName $AppId; Started = Get-Date; Ended = $null; NextTry = Get-Date }
}

function Sync-Recording($Session) {
    if ((Get-Date) -lt $Session.NextTry) { return }
    try {
        Start-ObsIfClosed
        if ((Invoke-Obs 'GetRecordStatus').outputActive) { return }
        New-Item -ItemType Directory -Force -Path $WorkFolder | Out-Null
        Invoke-Obs 'SetRecordDirectory' @{ recordDirectory = $WorkFolder } | Out-Null
        Invoke-Obs 'StartRecord' | Out-Null
        Write-Log "Recording $($Session.Name) ($($Session.AppId))"
    }
    catch {
        $Session.NextTry = (Get-Date).AddSeconds($RetrySeconds)
        Write-Log "Not recording $($Session.Name) yet: $($_.Exception.Message)"
    }
}

function Stop-ObsRecording {
    # Returns $false while OBS is open but cannot be reached, so the stop is tried again.
    try {
        if ((Invoke-Obs 'GetRecordStatus').outputActive) { Invoke-Obs 'StopRecord' | Out-Null }
        return $true
    }
    catch {
        if (-not (Test-ObsOpen)) { return $true }
        Write-Log "Could not stop OBS yet: $($_.Exception.Message)"
        return $false
    }
}

function Move-Recordings($Session) {
    # Every file OBS started while this game ran, including restarts after a crash or split files.
    $files = @(Get-ChildItem -LiteralPath $WorkFolder -File -ErrorAction SilentlyContinue |
        Where-Object { $_.CreationTime -ge $Session.Started -and $_.CreationTime -le $Session.Ended })
    $done = $true
    foreach ($file in $files) {
        if (-not (Test-FileClosed $file.FullName)) { $done = $false; continue }
        New-Item -ItemType Directory -Force -Path $ReadyFolder | Out-Null
        $target = Get-ReadyPath $Session $file
        Move-Item -LiteralPath $file.FullName -Destination $target
        Write-Log "Saved $target"
    }
    return $done
}

function Complete-Session($Session) {
    if (-not (Stop-ObsRecording)) { return $false }
    return Move-Recordings $Session
}

Write-Log "Loadout Recorder started, saving to $ReadyFolder"
$session = $null
$pending = New-Object Collections.ArrayList
while ($true) {
    try {
        $appId = Get-RunningGame
        if ($session -and $appId -ne $session.AppId) {
            $session.Ended = Get-Date
            [void]$pending.Add($session)
            $session = $null
        }
        foreach ($old in @($pending)) {
            if (Complete-Session $old) { $pending.Remove($old) }
            elseif ((Get-Date) -gt $old.Ended.AddMinutes($GiveUpMinutes)) {
                Write-Log "Gave up saving $($old.Name); its files stay in $WorkFolder"
                $pending.Remove($old)
            }
        }
        if ($appId -gt 0) {
            if (-not $session) { $session = New-Session $appId }
            Sync-Recording $session
        }
    }
    catch {
        try { Write-Log "Unexpected problem: $($_.Exception.Message)" } catch { }
    }
    Start-Sleep -Seconds $PollSeconds
}
