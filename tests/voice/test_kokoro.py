import pytest

from shorts.voice.tts import KokoroTTS


@pytest.mark.slow
@pytest.mark.parametrize("voice", ["af_heart", "am_michael"])
def test_kokoro_real(voice):
    audio, sr = KokoroTTS(1.0).synthesize("Hello world from ASUS.", voice)
    assert sr == 24000 and len(audio) / sr > 0.3


class _Result:
    audio = [0.0] * 2400


def test_each_voice_reads_at_its_own_speed(monkeypatch):
    # the voices talk at different paces at the same speed; each gets its own so all sound as lively
    tts = KokoroTTS(1.0, {"am_michael": 1.3})
    said = []
    monkeypatch.setattr(tts, "_pipeline", lambda voice: lambda text, voice, speed: said.append(speed) or [_Result()])
    tts.synthesize("Hi.", "am_michael")
    tts.synthesize("Hi.", "af_heart")
    assert said == [1.3, 1.0]


def test_a_line_can_be_read_at_its_own_speed(monkeypatch):
    tts = KokoroTTS(1.0, {"am_michael": 1.3})
    said = []
    monkeypatch.setattr(tts, "_pipeline", lambda voice: lambda text, voice, speed: said.append(speed) or [_Result()])
    tts.synthesize("Will you?", "am_michael", speed=1.0)
    assert said == [1.0]
