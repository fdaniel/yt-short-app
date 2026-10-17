"""Narration audio built line by line, so each line's timing is known exactly."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from shorts.voice.tts import TTSEngine


@dataclass(frozen=True)
class NarrationLine:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Narration:
    audio_path: Path
    duration: float
    lines: tuple[NarrationLine, ...]


def build_narration(lines: list[str], tts: TTSEngine, out_wav: Path, gap_s: float = 0.15) -> Narration:
    if not lines:
        raise ValueError("narration needs at least one line")
    pieces: list[np.ndarray] = []
    timed: list[NarrationLine] = []
    cursor = 0.0
    sample_rate = None
    for i, text in enumerate(lines):
        audio, sample_rate = tts.synthesize(text)
        if i > 0:
            pieces.append(np.zeros(int(round(gap_s * sample_rate)), np.float32))
            cursor += gap_s
        duration = len(audio) / sample_rate
        timed.append(NarrationLine(text=text, start=cursor, end=cursor + duration))
        pieces.append(audio.astype(np.float32))
        cursor += duration
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    samples = np.concatenate(pieces)
    sf.write(out_wav, samples, sample_rate)
    return Narration(audio_path=out_wav, duration=len(samples) / sample_rate, lines=tuple(timed))
