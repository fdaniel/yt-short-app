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


def voice_for(video_id: int, voices: tuple[str, ...]) -> str:
    """Videos take turns between the voices, so the channel has both a female and a male narrator."""
    return voices[(video_id - 1) % len(voices)]


def build_narration(
    lines: list[str], tts: TTSEngine, out_wav: Path, voice: str, gap_s: float = 0.15, lead_s: float = 0.0,
    *, closing_speed: float | None = None, closing_gap_s: float | None = None,
    sign_off: str = "", sign_off_gap_s: float = 0.5,
) -> Narration:
    """The lines one after another, after `lead_s` of silence; each line's start and end are kept.

    The last line, the question to viewers, may be read at its own speed after its own pause; a
    `sign_off` ("Tell us in the comments!") follows it at the same speed, after a breath of its own.
    """
    if not lines:
        raise ValueError("narration needs at least one line")
    spoken = [*lines, sign_off] if sign_off else list(lines)
    closing_at = len(lines) - 1
    pieces: list[np.ndarray] = []
    timed: list[NarrationLine] = []
    cursor = 0.0
    sample_rate = None
    for i, text in enumerate(spoken):
        calm = 0 < closing_at <= i
        audio, sample_rate = tts.synthesize(text, voice, closing_speed if calm else None)
        if i == 0:
            pause = lead_s
        elif i == len(lines):
            pause = sign_off_gap_s
        elif i == closing_at and closing_gap_s is not None:
            pause = closing_gap_s
        else:
            pause = gap_s
        if pause > 0:
            pieces.append(np.zeros(int(round(pause * sample_rate)), np.float32))
            cursor += pause
        duration = len(audio) / sample_rate
        timed.append(NarrationLine(text=text, start=cursor, end=cursor + duration))
        pieces.append(audio.astype(np.float32))
        cursor += duration
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    samples = np.concatenate(pieces)
    sf.write(out_wav, samples, sample_rate)
    return Narration(audio_path=out_wav, duration=len(samples) / sample_rate, lines=tuple(timed))
