"""Command line for the dashboard and the YouTube connection."""

import subprocess
import sys
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


def dashboard_command(settings: Settings, port: int, open_browser: bool) -> int:
    try:
        server = DashboardServer(Dashboard(settings, _account(settings), opener=open_on_windows), port=port)
    except OSError as exc:
        print(f"Could not start the dashboard on port {port} ({exc}). Is it already open? "
              f"Otherwise try another port: --port {port + 1}", file=sys.stderr)
        return 1
    url = f"http://localhost:{port}/"
    print(f"Dashboard running at {url}\nLeave this window open; press Ctrl+C to stop it.")
    if open_browser:
        try:
            open_on_windows(url)
        except OSError:
            pass  # the printed link is enough
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
