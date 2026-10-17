import pytest

from shorts.voice.tts import KokoroTTS


@pytest.mark.slow
def test_kokoro_real():
    audio, sr = KokoroTTS("af_heart", "a", 1.0).synthesize("Hello world.")
    assert sr == 24000 and len(audio) / sr > 0.3
