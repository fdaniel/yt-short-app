"""Command line for the dashboard and the YouTube connection."""

import subprocess
import sys
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path

from shorts.config import Settings
from shorts.dashboard.app import Dashboard
from shorts.dashboard.server import DashboardServer
from shorts.publish.youtube import NotConnected, YouTubeAccount


def open_on_windows(target: Path | str) -> None:
    """Show a folder in Windows Explorer, or a URL in the Windows browser (from inside WSL)."""
    if isinstance(target, Path):
        target = subprocess.run(["wslpath", "-w", str(target)], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.Popen(["explorer.exe", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _account(settings: Settings) -> YouTubeAccount:
    return YouTubeAccount(settings.data_dir / "youtube")


def _remaker(settings: Settings) -> Callable[[int, str], None]:
    """Re-makes a video with the owner's take, one at a time; the voice model loads on the first take only."""
    lock, loaded = threading.Lock(), {}

    def remake(video_id: int, take: str) -> None:
        from shorts.llm.chain import build_llm
        from shorts.net import build_http_client
        from shorts.pipeline import PipelineDeps, remake_with_take
        from shorts.storage.db import connect
        from shorts.voice.tts import KokoroTTS

        with lock:
            if "deps" not in loaded:
                http = build_http_client(settings)
                loaded["deps"] = PipelineDeps(http=http, llm=build_llm(settings, http), tts=KokoroTTS(settings.voice.speed))
            conn = connect(settings.data_dir / "shorts.db")
            try:
                remake_with_take(video_id, take, settings, loaded["deps"], conn)
            finally:
                conn.close()

    return remake


def _dashboard_running(port: int) -> bool:
    """Our own dashboard answers on this port (the desktop shortcut was clicked while it is open)."""
    request = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Host": f"localhost:{port}"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return b"review desk</title>" in response.read(4096)
    except OSError:
        return False


def _open(url: str) -> None:
    try:
        open_on_windows(url)
    except OSError:
        pass  # the printed link is enough


def dashboard_command(settings: Settings, port: int, open_browser: bool) -> int:
    try:
        dashboard = Dashboard(settings, _account(settings), opener=open_on_windows, remake=_remaker(settings))
        server = DashboardServer(dashboard, port=port)
    except OSError as exc:
        url = f"http://localhost:{port}/"
        if _dashboard_running(port):
            print(f"The dashboard is already running at {url}")
            if open_browser:
                _open(url)
            return 0
        print(f"Could not start the dashboard on port {port} ({exc}). Is it already open? "
              f"Otherwise try another port: --port {port + 1}", file=sys.stderr)
        return 1
    url = f"http://localhost:{port}/"
    print(f"Dashboard running at {url}\nLeave this window open; press Ctrl+C to stop it.")
    if open_browser:
        _open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
    return 0


def youtube_connect_command(settings: Settings) -> int:
    print("A Google page will open: sign in, pick the channel to upload to, and allow access.\n"
          "(If you closed that page, press Ctrl+C and run this again.)")
    try:
        channel = _account(settings).connect()
    except KeyboardInterrupt:
        print("\nConnection cancelled; nothing was changed.", file=sys.stderr)
        return 1
    except NotConnected as exc:
        print(f"Not connected: {exc}", file=sys.stderr)
        return 1
    print(f"Connected to the YouTube channel “{channel.title}”. The dashboard can now upload with one click.")
    return 0
