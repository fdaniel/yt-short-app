import pytest

from shorts.voice.tts import KokoroTTS


@pytest.mark.slow
@pytest.mark.parametrize("voice", ["af_heart", "am_michael"])
def test_kokoro_real(voice):
    audio, sr = KokoroTTS(1.0).synthesize("Hello world from ASUS.", voice)
    assert sr == 24000 and len(audio) / sr > 0.3
