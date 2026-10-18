"""Command line: `python -m shorts make-video|check-setup|run-once|schedule-help|topics`."""

import argparse
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from shorts import auto_cli
from shorts.config import ConfigError, Settings, load_settings
from shorts.llm.base import InvalidOutput, ProviderUnavailable
from shorts.llm.chain import build_llm
from shorts.llm.gemini import GeminiProvider
from shorts.models import VideoFormat
from shorts.music import licensed_tracks
from shorts.net import build_http_client
from shorts.pipeline import PipelineDeps, PipelineError, make_video
from shorts.storage.db import connect
from shorts.voice.tts import KokoroTTS

MIN_FREE_GB = 10


class _Ping(BaseModel):
    ok: bool


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shorts", description="Tech and gaming news Shorts, made legally.")
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("make-video", help="make one video from an official news URL")
    make.add_argument("--news-url", required=True)
    make.add_argument("--steam-app-id", type=int)
    make.add_argument("--format", default=VideoFormat.NEWS_FLASH.value, choices=[f.value for f in VideoFormat])
    make.add_argument("--config", default="config.yaml", type=Path)
    check = sub.add_parser("check-setup", help="check tools, keys and folders")
    check.add_argument("--config", default="config.yaml", type=Path)
    auto = sub.add_parser("run-once", help="automatic mode: find the best fresh story and make its video")
    auto.add_argument("--config", default="config.yaml", type=Path)
    auto.add_argument("--log-file", type=Path, help="default: <data_dir>/run.log")
    schedule = sub.add_parser("schedule-help", help="print the Windows command that runs automatic mode every 3 hours")
    schedule.add_argument("--config", default="config.yaml", type=Path)
    topics = sub.add_parser("topics", help="recent stories and why they were picked or skipped")
    topics.add_argument("--last", type=int, default=10)
    topics.add_argument("--config", default="config.yaml", type=Path)
    return parser


def _make_video(args: argparse.Namespace, settings: Settings) -> int:
    conn = connect(settings.data_dir / "shorts.db")
    try:
        with build_http_client(settings) as http:
            deps = PipelineDeps(
                http=http,
                llm=build_llm(settings, http),
                tts=KokoroTTS(settings.voice.kokoro_voice, settings.voice.lang_code, settings.voice.speed),
            )
            result = make_video(args.news_url, args.steam_app_id, VideoFormat(args.format), settings, deps, conn)
    except PipelineError as exc:
        print(f"Video failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Video ready for review (#{result.video_id}):\n  {result.video_path}\n  {result.metadata_path}")
    return 0


def probe_gemini(settings: Settings) -> tuple[bool, str]:
    try:
        GeminiProvider(settings.gemini_api_key, settings.llm.gemini_model).generate_json(
            'Reply with the JSON {"ok": true}.', _Ping
        )
    except (ProviderUnavailable, InvalidOutput) as exc:
        return False, str(exc)
    return True, f"Gemini ({settings.llm.gemini_model}) answered"


def _ffmpeg_check() -> tuple[bool, str]:
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg not found (sudo apt install ffmpeg)"
    filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    if " subtitles " not in filters:
        return False, "ffmpeg found but without libass (captions will not render)"
    return True, "ffmpeg with caption support"


def _free_space(settings: Settings) -> tuple[bool, str]:
    target = settings.data_dir
    while not target.exists():
        target = target.parent
    free_gb = shutil.disk_usage(target).free / 1024**3
    return free_gb >= MIN_FREE_GB, f"{free_gb:.0f} GB free for {settings.data_dir}"


def _checks(settings: Settings) -> list[tuple[str, bool, str]]:
    """(level, ok, message); level 'critical' failures make the command fail."""
    licensed = len(licensed_tracks(settings.music_dir))
    return [
        ("critical", *_ffmpeg_check()),
        ("critical", settings.font_file.is_file(), f"font file {settings.font_file}"),
        ("critical", True, "GEMINI_API_KEY is set"),
        ("critical", *probe_gemini(settings)),
        ("critical", importlib.util.find_spec("kokoro") is not None, "Kokoro voice installed"),
        ("warning", settings.fallback_api_key is not None, "fallback AI key (FALLBACK_LLM_API_KEY)"),
        ("warning", licensed > 0, f"{licensed} licensed music track(s) in {settings.music_dir}"),
        ("warning", *_free_space(settings)),
    ]


def _check_setup(settings: Settings) -> int:
    failed = False
    for level, ok, message in _checks(settings):
        mark = "✓" if ok else ("✗" if level == "critical" else "!")
        print(f" {mark} {message}")
        failed = failed or (level == "critical" and not ok)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_dotenv(Path.cwd() / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings(args.config, os.environ)
    except ConfigError as exc:
        print(f"Setup problem: {exc}", file=sys.stderr)
        return 1
    if args.command == "check-setup":
        return _check_setup(settings)
    if args.command == "run-once":
        return auto_cli.run_once_command(settings, args.log_file)
    if args.command == "schedule-help":
        return auto_cli.schedule_help(args.config)
    if args.command == "topics":
        return auto_cli.topics_command(settings, args.last)
    return _make_video(args, settings)
