"""Text-to-speech engines."""

from typing import Protocol

import numpy as np

KOKORO_SAMPLE_RATE = 24000


class TTSEngine(Protocol):
    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Return mono float32 samples and their sample rate."""
        ...


class KokoroTTS:
    """Open-source Kokoro voice, running locally on CPU."""

    def __init__(self, voice: str, lang_code: str, speed: float) -> None:
        self._voice, self._lang_code, self._speed = voice, lang_code, speed
        self._pipeline = None

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        if self._pipeline is None:
            from kokoro import KPipeline  # heavy import, only when actually speaking

            self._pipeline = KPipeline(lang_code=self._lang_code)
        parts = [
            np.asarray(result.audio, dtype=np.float32)
            for result in self._pipeline(text, voice=self._voice, speed=self._speed)
            if result.audio is not None
        ]
        if not parts:
            raise ValueError(f"Kokoro produced no audio for: {text!r}")
        return np.concatenate(parts), KOKORO_SAMPLE_RATE
