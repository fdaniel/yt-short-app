"""Decide how a horizontal shot becomes a 9:16 frame."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np

_PORTRAIT_SLACK = 1.05
_SAMPLES = 5
_SUBJECT_RATIO = 1.15


class CropMode(StrEnum):
    SMART = "smart"
    CENTER = "center"
    BLURRED = "blurred"


@dataclass(frozen=True)
class CropPlan:
    mode: CropMode
    x: int | None = None


def _column_energy(capture: cv2.VideoCapture, start: float, end: float) -> np.ndarray | None:
    profiles = []
    for t in np.linspace(start, max(start, end - 0.05), _SAMPLES):
        capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = capture.read()
        if not ok:
            continue
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        magnitude = np.abs(cv2.Sobel(grey, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(grey, cv2.CV_32F, 0, 1))
        profiles.append(magnitude.sum(axis=0))
    return np.mean(profiles, axis=0) if profiles else None


def choose_crop(video: Path, start: float, end: float) -> CropPlan:
    capture = cv2.VideoCapture(str(video))
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width <= height * 9 / 16 * _PORTRAIT_SLACK:
            return CropPlan(CropMode.CENTER)
        energy = _column_energy(capture, start, end)
    finally:
        capture.release()
    if energy is None:
        return CropPlan(CropMode.BLURRED)
    window = round(height * 9 / 16)
    sums = np.convolve(energy, np.ones(window), mode="valid")
    mean = float(sums.mean())
    best = int(np.argmax(sums))
    if mean == 0 or sums[best] / mean < _SUBJECT_RATIO:
        return CropPlan(CropMode.BLURRED)
    return CropPlan(CropMode.SMART, best)
