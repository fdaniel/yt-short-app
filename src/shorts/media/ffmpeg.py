"""Thin, safe wrappers around ffmpeg/ffprobe (argument lists only, never a shell)."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

_BASE = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
_STDERR_LINES = 20


class FFmpegError(Exception):
    """ffmpeg or ffprobe failed."""


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    duration: float
    has_audio: bool


def _tail(text: str) -> str:
    return "\n".join(text.strip().splitlines()[-_STDERR_LINES:])


def _run(cmd: list[str], *, timeout_s: int, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"{cmd[0]} timed out after {timeout_s} s") from exc
    if result.returncode != 0:
        raise FFmpegError(f"{cmd[0]} failed:\n{_tail(result.stderr)}")
    return result.stdout


def run_ffmpeg(args: list[str], *, timeout_s: int, cwd: Path | None = None) -> None:
    _run([*_BASE, *args], timeout_s=timeout_s, cwd=cwd)


def probe_video(path: Path) -> VideoInfo:
    out = _run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        timeout_s=60,
    )
    data = json.loads(out)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise FFmpegError(f"{path.name} has no video stream")
    return VideoInfo(
        width=int(video["width"]),
        height=int(video["height"]),
        duration=float(data.get("format", {}).get("duration", 0.0)),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def strip_audio(src: Path, dest: Path, *, timeout_s: int) -> Path:
    run_ffmpeg(["-i", str(src), "-an", "-c:v", "copy", str(dest)], timeout_s=timeout_s)
    return dest


def download_hls(url: str, dest: Path, *, max_seconds: int, timeout_s: int) -> Path:
    run_ffmpeg(
        ["-i", url, "-t", str(max_seconds), "-an", "-c:v", "copy", str(dest)], timeout_s=timeout_s
    )
    return dest
