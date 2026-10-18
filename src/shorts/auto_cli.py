"""Command line for automatic mode: run-once, schedule-help and topics."""

import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from shorts.config import Settings
from shorts.discovery.runner import RunLocked, run_once
from shorts.llm.chain import build_llm
from shorts.net import build_http_client
from shorts.pipeline import PipelineDeps
from shorts.storage.db import connect
from shorts.storage.topics import TopicRepository
from shorts.voice.tts import KokoroTTS

log = logging.getLogger(__name__)
LOG_MAX_BYTES = 5 * 1024 * 1024
TASK_NAME = "TechShorts"
DEFAULT_LOG = Settings.model_fields["data_dir"].default.expanduser() / "run.log"


def _say(message: str) -> None:
    print(message)
    log.info(message)


def _log_to_file(path: Path) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=2, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(min(root.level or logging.WARNING, logging.INFO))
    return handler


@contextmanager
def _file_log(path: Path) -> Iterator[None]:
    handler = _log_to_file(path)
    try:
        yield
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()


def run_once_command(settings: Settings, log_file: Path | None) -> int:
    with _file_log(log_file or settings.data_dir / "run.log"):
        try:
            return _run_and_report(settings)
        except Exception:
            log.exception("Run crashed")
            print("Run crashed; details in the log.", file=sys.stderr)
            return 1


def setup_problem(message: str, log_file: Path | None) -> None:
    """Scheduled runs throw away stderr: record setup problems where the owner will look."""
    with _file_log(log_file or DEFAULT_LOG):
        log.error("Setup problem, automatic mode cannot run: %s", message)


def _run_and_report(settings: Settings) -> int:
    conn = connect(settings.data_dir / "shorts.db")
    try:
        with build_http_client(settings) as http:
            tts = KokoroTTS(settings.voice.kokoro_voice, settings.voice.lang_code, settings.voice.speed)
            deps = PipelineDeps(http=http, llm=build_llm(settings, http), tts=tts)
            report = run_once(settings, deps, conn, now=datetime.now(UTC))
    except RunLocked:
        _say("Another run is still working; skipping this one.")
        return 0
    finally:
        conn.close()
    for result in report.made:
        _say(f"Made video #{result.video_id}: {result.video_path}")
    if report.skipped_reason:
        _say(f"No video this run: {report.skipped_reason}")
    log.info("Run finished: %d made, reason=%s, %d stories considered",
             len(report.made), report.skipped_reason, report.considered)
    return 0


def schedule_help(config_path: Path) -> int:
    distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu")
    repo = config_path.resolve().parent
    command = f"wsl.exe -d {distro} --cd {repo} -- {sys.executable} -m shorts run-once"
    print("Paste this into PowerShell (Windows, not Ubuntu) to run automatic mode every 3 hours:\n")
    print(f'  schtasks /Create /F /TN "{TASK_NAME}" /SC HOURLY /MO 3 /TR "{command}"\n')
    print("To stop automatic mode:\n")
    print(f'  schtasks /Delete /TN "{TASK_NAME}" /F\n')
    print("It runs while you are logged in to Windows; a console window may flash briefly.")
    return 0


def topics_command(settings: Settings, last: int) -> int:
    conn = connect(settings.data_dir / "shorts.db")
    try:
        rows = TopicRepository(conn).latest(last)
    finally:
        conn.close()
    if not rows:
        print("No topics yet. Run: python -m shorts run-once")
    for row in rows:
        score = "  -  " if row["score"] is None else f"{row['score']:.2f}"
        print(f"{row['status']:<8} {score}  {row['title']}  [{row['source']}]\n         {row['explanation']}")
    return 0
