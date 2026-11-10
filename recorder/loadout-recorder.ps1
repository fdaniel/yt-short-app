<#
.SYNOPSIS
Loadout Recorder: saves short clips of your Steam games with OBS, hands-free.

.DESCRIPTION
Runs in the background on the gaming PC. Nothing records continuously. While
Steam runs a game it keeps the OBS replay buffer on (the last 60 seconds of
play, held in memory), saving into the work folder; it restarts OBS or the
buffer if either stops. Every AutoSaveSeconds (60 by default, 0 turns it off)
it asks OBS to save a clip; you can save one yourself any time with the OBS
"Save Replay" hotkey (F9 suggested).

Every few seconds it moves each finished clip into the ready folder, named
after the game and how it was saved, for example
1492070_Crimson-Desert_2026-11-10_21-05-33_auto.mp4 (automatic save) or
..._pick.mp4 (your hotkey), so the Loadout Daily app knows which game it shows
and which clips you chose. Work and ready folders sit on the same drive, so a
clip appears in the ready folder (which Syncthing shares) only when complete.
When the game closes it turns the replay buffer off.

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
    [int]$GiveUpMinutes = 15,
    [int]$AutoSaveSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$LogFile = Join-Path (Split-Path $SettingsFile) 'recorder.log'
$ObsProcess = [IO.Path]::GetFileNameWithoutExtension($ObsExe)
$TimeoutMs = 10000
# How long to wait for OBS to name the clip an automatic save made before giving up on that name.
$AutoWaitSeconds = 30
$ReplayBufferHelp = 'OBS has the replay buffer turned off. In OBS open Settings > Output > Replay Buffer, ' +
    'tick Enable Replay Buffer, set Maximum Replay Time to 60 seconds and press OK.'

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

function Get-PathKey([string]$Path) {
    # OBS reports Windows paths with forward slashes; compare them the way Windows does.
    return $Path.Replace('/', '\').ToLowerInvariant()
}

function Get-ReadyPath($Session, $File, [string]$Tag) {
    $base = '{0}_{1}_{2:yyyy-MM-dd_HH-mm-ss}' -f $Session.AppId, (Get-SafeName $Session.Name), $File.CreationTime
    $target = Join-Path $ReadyFolder ('{0}_{1}{2}' -f $base, $Tag, $File.Extension)
    $copy = 2
    while (Test-Path -LiteralPath $target) {
        $target = Join-Path $ReadyFolder ('{0}-{1}_{2}{3}' -f $base, $copy, $Tag, $File.Extension)
        $copy++
    }
    return $target
}

function New-Session([int]$AppId) {
    return @{
        AppId = $AppId; Name = Get-GameName $AppId; Started = Get-Date; Ended = $null; NextTry = Get-Date
        NextSave = Get-Date; AutoSince = $null; AutoClips = New-Object 'Collections.Generic.HashSet[string]'
    }
}

function Get-LastReplay {
    # Empty while OBS is still writing a clip, before the first one, or when OBS cannot answer;
    # all of these just mean "ask again on the next round".
    try {
        $reply = Invoke-Obs 'GetLastReplayBufferReplay'
        if ($reply -and $reply.PSObject.Properties['savedReplayPath'] -and $reply.savedReplayPath) {
            return [string]$reply.savedReplayPath
        }
    }
    catch { }
    return ''
}

function Test-NewClip([string]$Path, [datetime]$Since) {
    $file = $Path.Replace('/', '\')
    return [IO.File]::Exists($file) -and [IO.File]::GetCreationTime($file) -ge $Since
}

function Save-AutoClip($Session) {
    if ($AutoSaveSeconds -le 0 -or $Session.AutoSince -or (Get-Date) -lt $Session.NextSave) { return }
    $since = Get-Date
    Invoke-Obs 'SaveReplayBuffer' | Out-Null
    $Session.AutoSince = $since
    $Session.NextSave = $since.AddSeconds($AutoSaveSeconds)
}

function Resolve-AutoClip($Session) {
    # OBS saves in the background, so the clip it names must be newer than the save request.
    if (-not $Session.AutoSince) { return }
    $path = Get-LastReplay
    if ($path -and (Test-NewClip $path $Session.AutoSince)) {
        [void]$Session.AutoClips.Add((Get-PathKey $path))
        $Session.AutoSince = $null
    }
    elseif ((Get-Date) -gt $Session.AutoSince.AddSeconds($AutoWaitSeconds)) {
        Write-Log ('OBS did not report the automatic clip asked for at {0:HH:mm:ss}' -f $Session.AutoSince)
        $Session.AutoSince = $null
    }
}

function Start-ClipBuffer($Session) {
    New-Item -ItemType Directory -Force -Path $WorkFolder | Out-Null
    Invoke-Obs 'SetRecordDirectory' @{ recordDirectory = $WorkFolder } | Out-Null
    Invoke-Obs 'StartReplayBuffer' | Out-Null
    $Session.AutoSince = $null
    $Session.NextSave = (Get-Date).AddSeconds($AutoSaveSeconds)
    Write-Log "Replay buffer on for $($Session.Name) ($($Session.AppId))"
}

function Write-ClipProblem($Session, [string]$Why) {
    Write-Log "Not clipping $($Session.Name) yet: $Why"
    if ($Why -match '^OBS refused (GetReplayBufferStatus|StartReplayBuffer)') { Write-Log $ReplayBufferHelp }
}

function Sync-ReplayBuffer($Session) {
    if ((Get-Date) -lt $Session.NextTry) { return }
    try {
        Start-ObsIfClosed
        if (-not (Invoke-Obs 'GetReplayBufferStatus').outputActive) { Start-ClipBuffer $Session; return }
        Save-AutoClip $Session
        Resolve-AutoClip $Session
    }
    catch {
        $Session.NextTry = (Get-Date).AddSeconds($RetrySeconds)
        Write-ClipProblem $Session $_.Exception.Message
    }
}

function Stop-ReplayBuffer {
    # Returns $false while OBS is open but cannot be reached, so the stop is tried again.
    # A refusal is an answer: OBS is reachable and has no replay buffer running.
    try {
        if ((Invoke-Obs 'GetReplayBufferStatus').outputActive) { Invoke-Obs 'StopReplayBuffer' | Out-Null }
        return $true
    }
    catch {
        if (-not (Test-ObsOpen) -or $_.Exception.Message -like 'OBS refused*') { return $true }
        Write-Log "Could not stop the OBS replay buffer yet: $($_.Exception.Message)"
        return $false
    }
}

function Test-SessionClip($Session, $File) {
    $created = $File.CreationTime
    if ($created -lt $Session.Started) { return $false }
    if ($Session.Ended) { return $created -le $Session.Ended }
    # Hold newer clips until OBS says which one the automatic save made, so it gets the right name.
    return (-not $Session.AutoSince) -or $created -lt $Session.AutoSince
}

function Get-ClipTag($Session, $File) {
    if ($Session.AutoClips.Contains((Get-PathKey $File.FullName))) { return 'auto' }
    return 'pick'
}

function Move-Clips($Session) {
    # Every finished clip OBS saved while this game ran, automatic or by hotkey.
    $files = @(Get-ChildItem -LiteralPath $WorkFolder -File -ErrorAction SilentlyContinue |
        Where-Object { Test-SessionClip $Session $_ })
    $done = $true
    foreach ($file in $files) {
        if (-not (Test-FileClosed $file.FullName)) { $done = $false; continue }
        New-Item -ItemType Directory -Force -Path $ReadyFolder | Out-Null
        $target = Get-ReadyPath $Session $file (Get-ClipTag $Session $file)
        Move-Item -LiteralPath $file.FullName -Destination $target
        Write-Log "Saved $target"
    }
    return $done
}

function Complete-Session($Session) {
    Resolve-AutoClip $Session
    if (-not (Stop-ReplayBuffer)) { return $false }
    return Move-Clips $Session
}

Write-Log "Loadout Recorder started, saving clips to $ReadyFolder"
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
            Sync-ReplayBuffer $session
            Move-Clips $session | Out-Null
        }
    }
    catch {
        try { Write-Log "Unexpected problem: $($_.Exception.Message)" } catch { }
    }
    Start-Sleep -Seconds $PollSeconds
}
