"""The brand's sound: a whoosh as the slash crosses, two rising notes as the outro badge lands.

Made from noise and sine waves here, so no licence is needed.
"""

from pathlib import Path

import numpy as np
import soundfile as sf

RATE = 48000
_NOTES = (659.25, 987.77)  # E5 then B5: a rising fifth
_CHIME_DELAY_S = 0.2  # the notes land with the outro badge
_INTRO_WHOOSH_S = 0.45
# the first word waits for the whoosh to pass: spoken under it, the hook was hard to make out
VOICE_LEAD_S = 0.4


def _whoosh(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Noise whose brightness rises then falls, swelling in and out: air rushing past."""
    n = int(seconds * RATE)
    noise = rng.standard_normal(n).astype(np.float32)
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    bright = 0.04 + 0.5 * np.sin(np.pi * t) ** 2  # one-pole low-pass amount per sample
    out = np.empty(n, np.float32)
    level = 0.0
    for i in range(n):
        level += bright[i] * (noise[i] - level)
        out[i] = level
    envelope = np.clip(np.sin(np.pi * t), 0.0, 1.0) ** 1.5  # sin(pi) rounds below zero
    return out * envelope / (np.abs(out).max() or 1.0)


def _chime() -> np.ndarray:
    parts = []
    for k, freq in enumerate(_NOTES):
        length = 0.09 if k == 0 else 0.32
        t = np.arange(int(length * RATE), dtype=np.float32) / RATE
        tone = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t)
        parts.append(tone * np.exp(-t * (18 if k == 0 else 9)) * np.minimum(1.0, t / 0.004))
    return np.concatenate(parts).astype(np.float32) * 0.5


def _place(track: np.ndarray, sound: np.ndarray, at_s: float, gain: float) -> None:
    start = int(at_s * RATE)
    end = min(len(track), start + len(sound))
    if start < end:
        track[start:end] += gain * sound[: end - start]


def write_sting(narration_s: float, total_s: float, out: Path) -> Path:
    """One track as long as the video: a whoosh at the start, whoosh and chime at the end, silence between."""
    rng = np.random.default_rng(7)  # the same sound every video
    track = np.zeros(int(total_s * RATE) + 1, np.float32)
    _place(track, _whoosh(_INTRO_WHOOSH_S, rng), 0.0, 0.55)
    _place(track, _whoosh(0.4, rng), narration_s - 0.12, 0.55)
    _place(track, _chime(), narration_s + _CHIME_DELAY_S, 0.45)
    sf.write(out, np.clip(track, -1.0, 1.0), RATE)
    return out
