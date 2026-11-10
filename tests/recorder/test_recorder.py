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
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise AssertionError(f"PowerShell failed: {command}\n{result.stderr}")
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


class Refused(Exception):
    """OBS answered a request with result false and this comment."""


class FakeObs:
    """Speaks just enough obs-websocket v5 to run a replay buffer.

    Like OBS, each save (by request or by the owner's hotkey) writes a new `Replay <n>.mp4` into the record
    directory and becomes the "last replay", reported as a Windows path with forward slashes (upper-cased here
    to prove the recorder compares paths without caring about case or slash style).
    """

    def __init__(self, password: str, refuse_replay: str = "", save_delay: float = 0.0):
        self.password = password
        self.refuse_replay = refuse_replay
        self.save_delay = save_delay
        self.requests: list[str] = []
        self.active = False
        self.directory = None
        self.windows_directory = ""
        self.files: list[Path] = []
        self.last_replay = ""
        self._lock = threading.Lock()

    def started(self) -> int:
        return self.requests.count("StartReplayBuffer")

    def stop_on_its_own(self) -> None:
        self.active = False

    def press_save_hotkey(self) -> Path:
        """The owner presses "Save Replay": OBS writes a clip without any WebSocket request."""
        return self._save()

    def record_by_hand(self, name: str = "2026-11-10 21-05-33.mp4") -> Path:
        """The owner presses Start and then Stop Recording: OBS writes a normal recording, not a Replay file."""
        path = self.directory / name
        path.write_bytes(b"fake recording")
        return path

    def _save(self) -> Path:
        with self._lock:
            name = f"Replay {len(self.files) + 1}.mp4"
            path = self.directory / name
            self.files.append(path)
            path.write_bytes(b"fake clip")
            self.last_replay = (self.windows_directory.upper() + "\\" + name).replace("\\", "/")
            return path

    def _answer(self, request: dict) -> dict:
        kind = request["requestType"]
        if kind == "GetReplayBufferStatus":
            return {"outputActive": self.active}
        if kind == "SetRecordDirectory":
            self.windows_directory = request["requestData"]["recordDirectory"]
            self.directory = _wsl(self.windows_directory)
        elif kind == "StartReplayBuffer":
            if self.refuse_replay:
                raise Refused(self.refuse_replay)
            self.active = True
        elif kind == "StopReplayBuffer":
            self.active = False
        elif kind == "SaveReplayBuffer":
            if self.save_delay:
                threading.Timer(self.save_delay, self._save).start()
            else:
                self._save()
        elif kind == "GetLastReplayBufferReplay":
            return {"savedReplayPath": self.last_replay}
        elif kind in ("StartRecord", "StopRecord", "GetRecordStatus"):
            raise Refused(f"{kind} must not be used any more")
        return {}

    def _reply(self, request: dict) -> dict:
        self.requests.append(request["requestType"])
        reply = {"requestType": request["requestType"], "requestId": request["requestId"]}
        try:
            reply["responseData"] = self._answer(request)
            reply["requestStatus"] = {"result": True, "code": 100}
        except Refused as refusal:
            reply["requestStatus"] = {"result": False, "code": 604, "comment": str(refusal)}
        return reply

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
            ws.send(json.dumps({"op": 7, "d": self._reply(json.loads(raw)["d"])}))


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
    # auto_save 0 (no automatic saves) keeps the tests that only need hotkey clips predictable.
    def _start(obs_password: str, saved_password: str, steam_process: str = "powershell",
               auto_save: int = 0, retry: int = 60, **obs_options):
        _ps(f"$p = ConvertTo-SecureString '{saved_password}' -AsPlainText -Force | ConvertFrom-SecureString; "
            f"@{{ obs_password = $p }} | ConvertTo-Json | Set-Content '{folder}\\settings.json'")
        obs = FakeObs(obs_password, **obs_options)
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
            "-AutoSaveSeconds", str(auto_save), "-RetrySeconds", str(retry),
        ])
        started.append((process, server))
        return obs, local

    yield _start
    for process, server in started:
        process.kill()
        process.wait()
        server.shutdown()


def _log(local: Path) -> str:
    log = local / "recorder.log"
    return log.read_text() if log.exists() else ""


def test_a_steam_game_runs_the_replay_buffer_in_the_work_folder_and_never_records(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2")

    _set_running(steam_key, 1492070)
    _wait_for(lambda: obs.active)
    _set_running(steam_key, 0)
    _wait_for(lambda: "StopReplayBuffer" in obs.requests)

    assert obs.directory == local / "work"
    assert obs.requests.index("SetRecordDirectory") < obs.requests.index("StartReplayBuffer")
    assert obs.started() == 1
    assert "StartRecord" not in obs.requests
    assert not obs.active
    assert _ready(local) == []


def test_automatic_clips_are_sent_while_the_game_runs_and_end_in_auto(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2", auto_save=2)

    _set_running(steam_key, 1492070)
    _wait_for(lambda: len(_ready(local)) >= 2)

    assert obs.active, "the clips left while the game was still running"
    names = [path.name for path in _ready(local)]
    assert all(name.startswith("1492070_Sker-Ritual_") and name.endswith("_auto.mp4") for name in names), names
    assert _ready(local)[0].read_bytes() == b"fake clip"
    assert not obs.files[0].exists()
    assert obs.requests.index("SaveReplayBuffer") < obs.requests.index("GetLastReplayBufferReplay")


def test_a_clip_saved_with_the_hotkey_is_sent_while_the_game_runs_and_ends_in_pick(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2")

    _set_running(steam_key, 1492070)
    _wait_for(lambda: obs.active)
    obs.press_save_hotkey()
    _wait_for(lambda: len(_ready(local)) == 1)

    [saved] = _ready(local)
    assert saved.name.startswith("1492070_Sker-Ritual_")
    assert saved.name.endswith("_pick.mp4")
    assert obs.active
    assert "SaveReplayBuffer" not in obs.requests


def test_a_recording_made_by_hand_is_sent_and_ends_in_rec(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2")

    _set_running(steam_key, 1492070)
    _wait_for(lambda: obs.active)
    obs.record_by_hand()
    _wait_for(lambda: len(_ready(local)) == 1)

    [saved] = _ready(local)
    assert saved.name.startswith("1492070_Sker-Ritual_") and saved.name.endswith("_rec.mp4")
    assert saved.read_bytes() == b"fake recording"


def test_an_automatic_clip_that_obs_writes_a_moment_later_still_ends_in_auto(recorder, steam_key):
    # Real OBS saves in the background: right after SaveReplayBuffer it still reports the previous clip.
    obs, local = recorder("hunter2", "hunter2", auto_save=2, save_delay=2.5)

    _set_running(steam_key, 1492070)
    _wait_for(lambda: obs.active)
    obs.press_save_hotkey()
    _wait_for(lambda: any(path.name.endswith("_auto.mp4") for path in _ready(local)))

    names = [path.name for path in _ready(local)]
    assert sum(name.endswith("_pick.mp4") for name in names) == 1, names


def test_hotkey_clips_overlapping_automatic_saves_are_all_sent(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2", auto_save=1)

    _set_running(steam_key, 1492070)
    _wait_for(lambda: obs.active)
    for _ in range(10):
        obs.press_save_hotkey()
        time.sleep(0.4)
    _set_running(steam_key, 0)
    _wait_for(lambda: "StopReplayBuffer" in obs.requests)
    _wait_for(lambda: len(_ready(local)) == len(obs.files))

    names = [path.name for path in _ready(local)]
    assert all(name.endswith(("_auto.mp4", "_pick.mp4")) for name in names), names
    assert any(name.endswith("_pick.mp4") for name in names)
    assert any(name.endswith("_auto.mp4") for name in names)
    assert "Unexpected problem" not in _log(local)


def test_obs_without_the_replay_buffer_turned_on_is_told_in_plain_english_and_retried(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2", retry=2, refuse_replay="Replay buffer is not available.")

    _set_running(steam_key, 1492070)
    _wait_for(lambda: obs.started() >= 2)

    assert "Settings > Output > Replay Buffer" in _log(local)
    assert "StartRecord" not in obs.requests
    assert _ready(local) == []


def test_a_replay_buffer_that_stops_mid_game_is_restarted_and_every_clip_is_sent(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2")

    _set_running(steam_key, 1492070)
    _wait_for(lambda: obs.started() == 1)
    obs.press_save_hotkey()
    obs.stop_on_its_own()
    _wait_for(lambda: obs.started() == 2)
    obs.press_save_hotkey()
    _set_running(steam_key, 0)
    _wait_for(lambda: "StopReplayBuffer" in obs.requests)
    _wait_for(lambda: len(_ready(local)) == 2)

    names = [path.name for path in _ready(local)]
    assert all(name.startswith("1492070_Sker-Ritual_") for name in names)
    assert len(set(names)) == 2
    assert not obs.active


def test_a_game_without_a_name_in_steam_is_named_by_its_id(recorder, steam_key):
    obs, local = recorder("hunter2", "hunter2")

    _set_running(steam_key, 2076040)
    _wait_for(lambda: obs.started() == 1)
    obs.press_save_hotkey()
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
