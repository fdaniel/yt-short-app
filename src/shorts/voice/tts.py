"""Text-to-speech engines."""

from collections.abc import Mapping
from typing import Protocol

import numpy as np

from shorts.voice.pronounce import speakable

KOKORO_SAMPLE_RATE = 24000


class TTSEngine(Protocol):
    def synthesize(self, text: str, voice: str, speed: float | None = None) -> tuple[np.ndarray, int]:
        """Return mono float32 samples and their sample rate; `speed` overrides the voice's own."""
        ...


class KokoroTTS:
    """Open-source Kokoro voices, running locally on CPU."""

    def __init__(self, speed: float, speeds: Mapping[str, float] | None = None) -> None:
        self._speed = speed
        self._speeds = dict(speeds or {})  # per voice: at one speed some voices talk much slower than others
        self._pipelines: dict[str, object] = {}  # one per accent: a (American) or b (British) English

    def _pipeline(self, voice: str):
        lang_code = voice[0]
        if lang_code not in self._pipelines:
            from kokoro import KPipeline  # heavy import, only when actually speaking

            self._pipelines[lang_code] = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
        return self._pipelines[lang_code]

    def synthesize(self, text: str, voice: str, speed: float | None = None) -> tuple[np.ndarray, int]:
        speed = speed if speed is not None else self._speeds.get(voice, self._speed)
        parts = [
            np.asarray(result.audio, dtype=np.float32)
            for result in self._pipeline(voice)(speakable(text), voice=voice, speed=speed)
            if result.audio is not None
        ]
        if not parts:
            raise ValueError(f"Kokoro produced no audio for: {text!r}")
        return np.concatenate(parts), KOKORO_SAMPLE_RATE
