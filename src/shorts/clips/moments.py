"""Where the action is in a clip: the stretch with the loudest game sound and the most movement."""

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from shorts.media.ffmpeg import FFmpegError, probe_video

SAMPLE_RATE = 8000
SILENCE_DB = -60.0
LOUD_WEIGHT, MOTION_WEIGHT = 0.6, 0.4
MOTION_FPS = 2
MOTION_SIZE = (64, 36)
MAX_CLIP_S = 300  # longer files are whole recordings (the old recorder), not clips
END_LEAN = 0.5  # a pick's last seconds count up to 1.5 times: the owner pressed the key right after the moment


class ClipTooLong(ValueError):
    """A whole recording, not a clip: reading it would hold the app for too long."""


@dataclass(frozen=True)
class Moment:
    start: float
    end: float
    score: float  # loudness (dB) plus movement over the stretch: higher is more action, comparable between clips


def _spread(values: np.ndarray) -> np.ndarray:
    low, high = float(values.min()), float(values.max())
    return np.zeros_like(values) if high - low < 1e-9 else (values - low) / (high - low)


def best_window(loudness: Sequence[float], motion: Sequence[float], length_s: int, *, favour_end: bool) -> Moment:
    """The `length_s` seconds with the most action; the whole clip when it is shorter."""
    seconds = min(len(loudness), len(motion))
    if seconds == 0:
        raise ValueError("the clip has no seconds to measure")
    loud, moving = np.asarray(loudness[:seconds], float), np.asarray(motion[:seconds], float)
    action = LOUD_WEIGHT * _spread(loud) + MOTION_WEIGHT * _spread(moving)
    if favour_end:
        action = action * (1 + END_LEAN * np.arange(seconds) / max(1, seconds - 1)) + END_LEAN * np.arange(seconds) / max(1, seconds - 1)
    width = min(length_s, seconds)
    sums = np.convolve(action, np.ones(width), mode="valid")
    # ties go to the latest stretch for a pick, to the earliest otherwise
    start = len(sums) - 1 - int(np.argmax(sums[::-1])) if favour_end else int(np.argmax(sums))
    window = slice(start, start + width)
    return Moment(float(start), float(start + width), float(loud[window].mean() + moving[window].mean()))


def loudness_per_second(path: Path, timeout_s: int) -> list[float]:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
           "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    raw = _decoded(cmd, f"sound of {path.name}", timeout_s)
    samples = np.frombuffer(raw[: len(raw) // 2 * 2], dtype=np.int16).astype(float) / 32768
    seconds = len(samples) // SAMPLE_RATE
    if seconds == 0:
        return []
    rms = np.sqrt((samples[: seconds * SAMPLE_RATE].reshape(seconds, SAMPLE_RATE) ** 2).mean(axis=1))
    return [max(SILENCE_DB, 20 * float(np.log10(r))) if r > 0 else SILENCE_DB for r in rms]


def _decoded(cmd: list[str], what: str, timeout_s: int) -> bytes:
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"reading the {what} timed out after {timeout_s} s") from exc
    return result.stdout


def motion_per_second(path: Path, timeout_s: int) -> list[float]:
    """Average change between small greyscale frames, MOTION_FPS times a second."""
    width, height = MOTION_SIZE
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-an",
           "-vf", f"fps={MOTION_FPS},scale={width}:{height},format=gray", "-f", "rawvideo", "-"]
    raw = _decoded(cmd, f"picture of {path.name}", timeout_s)
    frames = np.frombuffer(raw[: len(raw) // (width * height) * width * height], dtype=np.uint8)
    frames = frames.reshape(-1, height, width).astype(float)
    if len(frames) < 2:
        return []
    diffs = [0.0, *np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2)).tolist()]
    return [float(np.mean(diffs[i:i + MOTION_FPS])) for i in range(0, len(diffs) - MOTION_FPS + 1, MOTION_FPS)]


def find_moment(path: Path, length_s: int, *, favour_end: bool, timeout_s: int, max_s: int = MAX_CLIP_S) -> Moment:
    seconds = probe_video(path).duration
    if seconds > max_s:
        raise ClipTooLong(f"{path.name} is {seconds / 60:.0f} min long: clips are at most {max_s // 60} min")
    loudness, motion = loudness_per_second(path, timeout_s), motion_per_second(path, timeout_s)
    if not motion:
        raise FFmpegError(f"{path.name} has no readable video")
    if not loudness:  # a clip without sound: movement alone decides
        loudness = [SILENCE_DB] * len(motion)
    return best_window(loudness, motion, length_s, favour_end=favour_end)
