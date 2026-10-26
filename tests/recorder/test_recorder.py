"""Loadout Recorder (Windows PowerShell) against a fake OBS WebSocket server and a test Steam registry key."""

import base64
import hashlib
import json
import shutil
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest
from websockets.sync.server import serve

pytestmark = pytest.mark.skipif(not shutil.which("powershell.exe"), reason="needs Windows PowerShell (WSL)")

SCRIPT = Path(__file__).parents[2] / "recorder" / "loadout-recorder.ps1"
SALT, CHALLENGE = "c2FsdA==", "Y2hhbGxlbmdl"


def _ps(command: str) -> str:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _wsl(windows_path: str) -> Path:
    return Path(subprocess.run(["wslpath", "-u", windows_path], capture_output=True, text=True, check=True).stdout.strip())


def _sha(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()


def _wait_for(check, seconds=40):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.5)
    raise AssertionError("timed out")


class FakeObs:
    """Speaks just enough obs-websocket v5 and, like OBS, writes a file into the record directory on each start."""

    def __init__(self, password: str):
        self.password = password
        self.requests: list[str] = []
        self.active = False
        self.directory = None
        self.files: list[Path] = []

    def started(self) -> int:
        return self.requests.count("StartRecord")

    def stop_on_its_own(self) -> None:
        self.active = False

    def _answer(self, request: dict) -> dict:
        kind = request["requestType"]
        if kind == "GetRecordStatus":
            return {"outputActive": self.active}
        if kind == "SetRecordDirectory":
            self.directory = _wsl(request["requestData"]["recordDirectory"])
        elif kind == "StartRecord":
            self.active = True
            self.files.append(self.directory / f"rec-{len(self.files) + 1}.mp4")
            self.files[-1].write_bytes(b"fake gameplay")
        elif kind == "StopRecord":
            self.active = False
            return {"outputPath": "unused"}
        return {}

    def handle(self, ws):
        hello = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1,
                 "authentication": {"challenge": CHALLENGE, "salt": SALT}}
        ws.send(json.dumps({"op": 0, "d": hello}))
        identify = json.loads(ws.recv())["d"]
        if identify.get("authentication") != _sha(_sha(self.password + SALT) + CHALLENGE):
            ws.close(4009, "Authentication failed.")
            return
        ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        for raw in ws:
            request = json.loads(raw)["d"]
            self.requests.append(request["requestType"])
            reply = {"requestType": request["requestType"], "requestId": request["requestId"],
                     "requestStatus": {"result": True, "code": 100}, "responseData": self._answer(request)}
            ws.send(json.dumps({"op": 7, "d": reply}))


@pytest.fixture
def windows_dir():
    temp = _ps("[IO.Path]::GetTempPath()")
    folder = temp.rstrip("\\") + f"\\loadout-recorder-test-{uuid.uuid4().hex[:8]}"
    local = _wsl(folder)
    local.mkdir()
    yield folder, local
    shutil.rmtree(local, ignore_errors=True)


@pytest.fixture
def steam_key():
    key = f"HKCU:\\Software\\LoadoutRecorderTest-{uuid.uuid4().hex[:8]}"
    _ps(f"New-Item -Path '{key}\\Apps\\1492070' -Force | Out-Null; "
        f"Set-ItemProperty -Path '{key}\\Apps\\1492070' -Name Name -Value 'Sker Ritual'; "
        f"New-ItemProperty -Path '{key}' -Name RunningAppID -PropertyType DWord -Value 0 | Out-Null")
    yield key
    _ps(f"Remove-Item -Path '{key}' -Recurse -Force")


def _set_running(key: str, app_id: int) -> None:
    _ps(f"Set-ItemProperty -Path '{key}' -Name RunningAppID -Value {app_id}")


def _ready(local: Path) -> list[Path]:
    folder = local / "ready"
    return sorted(folder.iterdir()) if folder.exists() else []


@pytest.fixture
def recorder(windows_dir, steam_key):
    folder, local = windows_dir
    started = []

    # steam_process: the recorder itself runs as powershell, so that name always counts as "Steam is running".
    def _start(obs_password: str, saved_password: str, steam_process: str = "powershell"):
        _ps(f"$p = ConvertTo-SecureString '{saved_password}' -AsPlainText -Force | ConvertFrom-SecureString; "
            f"@{{ obs_password = $p }} | ConvertTo-Json | Set-Content '{folder}\\settings.json'")
        obs = FakeObs(obs_password)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = serve(obs.handle, "127.0.0.1", port)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        script = subprocess.run(["wslpath", "-w", str(SCRIPT)], capture_output=True, text=True, check=True).stdout.strip()
        process = subprocess.Popen([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
            "-SteamKey", steam_key, "-SteamProcess", steam_process,
            "-ReadyFolder", f"{folder}\\ready", "-WorkFolder", f"{folder}\\work",
            "-ObsUrl", f"ws://127.0.0.1:{port}", "-SettingsFile", f"{folder}\\settings.json",
            "-ObsExe", f"{folder}\\no-obs.exe", "-PollSeconds", "1",
        ])
        started.append((process, server))
        return obs, local

    yield _start
    for process, server in started:
        process.kill()
        process.wait()
        server.shutdown()


def test_records_a_steam_game_and_names_the_file_after_it(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2")

    _set_running(steam_key, 1492070)
    _wait_for(lambda: obs.started() == 1)
    _set_running(steam_key, 0)
    _wait_for(lambda: len(_ready(local)) == 1)

    [saved] = _ready(local)
    assert saved.name.startswith("1492070_Sker-Ritual_")
    assert saved.suffix == ".mp4"
    assert saved.read_bytes() == b"fake gameplay"
    assert not obs.files[0].exists()
    assert obs.directory == local / "work"
    assert obs.requests.count("StopRecord") == 1
    assert not obs.active


def test_a_recording_that_stops_mid_game_is_restarted_and_both_parts_are_saved(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2")

    _set_running(steam_key, 1492070)
    _wait_for(lambda: obs.started() == 1)
    obs.stop_on_its_own()
    _wait_for(lambda: obs.started() == 2)
    _set_running(steam_key, 0)
    _wait_for(lambda: len(_ready(local)) == 2)

    names = [path.name for path in _ready(local)]
    assert all(name.startswith("1492070_Sker-Ritual_") for name in names)
    assert len(set(names)) == 2
    assert not obs.active


def test_a_game_without_a_name_in_steam_is_named_by_its_id(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2")

    _set_running(steam_key, 2076040)
    _wait_for(lambda: obs.started() == 1)
    _set_running(steam_key, 0)
    _wait_for(lambda: len(_ready(local)) == 1)

    assert _ready(local)[0].name.startswith("2076040_app-2076040_")


def test_a_game_left_in_the_registry_while_steam_is_closed_is_not_recorded(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2", steam_process="no-such-steam")

    _set_running(steam_key, 1492070)
    log = local / "recorder.log"
    _wait_for(lambda: log.exists() and "started" in log.read_text())
    time.sleep(4)

    assert obs.requests == []


def test_a_wrong_obs_password_records_nothing_and_the_log_says_why(recorder, steam_key):
    obs, local = recorder("hunter2", "not-the-password")

    _set_running(steam_key, 1492070)
    log = local / "recorder.log"
    _wait_for(lambda: log.exists() and "wrong WebSocket password" in log.read_text())

    assert obs.requests == []
    assert _ready(local) == []
