"""Find usable shots in a trailer and rank them by how much is happening."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from scenedetect import AdaptiveDetector, detect

from shorts.media.ffmpeg import probe_video

_SAMPLE_FPS = 2.0
_SAMPLE_WIDTH = 320
_BAR_LUMA = 20  # rows this dark are letterbox bars, not picture
_MIN_BRIGHTNESS = 40  # darker scenes read as a black screen on a phone


@dataclass(frozen=True)
class Shot:
    source: Path
    asset_id: int
    start: float
    end: float
    score: float


def _scenes(video: Path, duration: float) -> list[tuple[float, float]]:
    found = detect(str(video), AdaptiveDetector())
    if not found:
        return [(0.0, duration)]
    return [(start.seconds, end.seconds) for start, end in found]


def _small_frame(capture: cv2.VideoCapture, at: float) -> np.ndarray | None:
    capture.set(cv2.CAP_PROP_POS_MSEC, at * 1000)
    ok, frame = capture.read()
    if not ok:
        return None
    height = int(frame.shape[0] * _SAMPLE_WIDTH / frame.shape[1])
    return cv2.resize(frame, (_SAMPLE_WIDTH, height))


def _brightness(frame: np.ndarray) -> float:
    """Mean lightness (strongest colour channel, so pure blue is not "dark"), ignoring letterbox bars."""
    rows = frame.max(axis=2).astype(np.float32).mean(axis=1)
    picture = rows[rows >= _BAR_LUMA]
    return float(picture.mean()) if picture.size else 0.0


def _score(capture: cv2.VideoCapture, start: float, end: float) -> float | None:
    """How much moves in the scene; None when it is too dark to show."""
    times = np.arange(start, end, 1 / _SAMPLE_FPS)
    frames = [f for f in (_small_frame(capture, t) for t in times) if f is not None]
    if frames and float(np.median([_brightness(f) for f in frames])) < _MIN_BRIGHTNESS:
        return None
    if len(frames) < 2:
        return 0.0
    grey = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in frames]
    return float(np.mean([np.mean(np.abs(b - a)) for a, b in zip(grey, grey[1:])]))


def detect_shots(
    video: Path,
    asset_id: int,
    *,
    skip_head_s: float = 3.0,
    skip_tail_s: float = 8.0,
    min_len_s: float = 1.5,
) -> list[Shot]:
    """Bright-enough scenes inside [skip_head_s, duration - skip_tail_s], best (most motion) first."""
    duration = probe_video(video).duration
    window_start, window_end = skip_head_s, duration - skip_tail_s
    if window_end - window_start < min_len_s:
        return []
    capture = cv2.VideoCapture(str(video))
    try:
        shots = []
        for start, end in _scenes(video, duration):
            start, end = max(start, window_start), min(end, window_end)
            if end - start < min_len_s:
                continue
            score = _score(capture, start, end)
            if score is not None:
                shots.append(Shot(video, asset_id, start, end, score))
    finally:
        capture.release()
    return sorted(shots, key=lambda s: s.score, reverse=True)
