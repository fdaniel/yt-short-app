"""Decide how a horizontal shot becomes a 9:16 frame."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np

_PORTRAIT_SLACK = 1.05
_SAMPLES = 5
_SUBJECT_RATIO = 1.15
_BAR_LUMA = 20  # rows darker than this in every sample are letterbox bars
_MIN_BAR_SHARE = 0.03
_MIN_CONTENT_SHARE = 0.5


class CropMode(StrEnum):
    SMART = "smart"
    CENTER = "center"


@dataclass(frozen=True)
class CropPlan:
    """`top`/`height`: the picture inside letterbox bars (height None = the whole frame)."""

    mode: CropMode
    x: int | None = None
    top: int = 0
    height: int | None = None


def _grey_samples(capture: cv2.VideoCapture, start: float, end: float) -> list[np.ndarray]:
    frames = []
    for t in np.linspace(start, max(start, end - 0.05), _SAMPLES):
        capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = capture.read()
        if ok:
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32))
    return frames


def _content_rows(frames: list[np.ndarray]) -> tuple[int, int | None]:
    """(top, height) of the picture between black letterbox bars; (0, None) when there are none."""
    full = frames[0].shape[0]
    lit = np.flatnonzero(np.max([f.mean(axis=1) for f in frames], axis=0) >= _BAR_LUMA)
    if lit.size == 0:
        return 0, None
    top, bottom = int(lit[0]), full - 1 - int(lit[-1])
    height = full - top - bottom
    if max(top, bottom) < full * _MIN_BAR_SHARE or height < full * _MIN_CONTENT_SHARE:
        return 0, None
    even_top = top + top % 2  # even values for yuv420p, still inside the picture
    even_height = height - (even_top - top)
    return even_top, even_height - even_height % 2


def _column_energy(frames: list[np.ndarray]) -> np.ndarray:
    profiles = []
    for grey in frames:
        magnitude = np.abs(cv2.Sobel(grey, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(grey, cv2.CV_32F, 0, 1))
        profiles.append(magnitude.sum(axis=0))
    return np.mean(profiles, axis=0)


def choose_crop(video: Path, start: float, end: float) -> CropPlan:
    """Always a full 9:16 picture: follow the subject when there is one, else the centre."""
    capture = cv2.VideoCapture(str(video))
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width <= height * 9 / 16 * _PORTRAIT_SLACK:
            return CropPlan(CropMode.CENTER)
        frames = _grey_samples(capture, start, end)
    finally:
        capture.release()
    if not frames:
        return CropPlan(CropMode.CENTER)
    top, content_h = _content_rows(frames)
    if content_h is not None:
        frames = [f[top : top + content_h] for f in frames]
    window = round((content_h or height) * 9 / 16)
    sums = np.convolve(_column_energy(frames), np.ones(window), mode="valid")
    mean = float(sums.mean())
    best = int(np.argmax(sums))
    if mean == 0 or sums[best] / mean < _SUBJECT_RATIO:
        return CropPlan(CropMode.CENTER, top=top, height=content_h)
    return CropPlan(CropMode.SMART, best, top=top, height=content_h)
