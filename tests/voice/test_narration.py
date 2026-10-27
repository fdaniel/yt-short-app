import pytest
import soundfile as sf

from shorts.voice.narration import build_narration
from tests.fakes import FakeTTS


def test_narration_timing(tmp_path):
    n = build_narration(["Hello there.", "Second line here."], FakeTTS(), tmp_path / "n.wav", "af_heart")
    assert n.lines[0].start == 0
    assert n.lines[0].end == pytest.approx(len("Hello there.") * 0.05, abs=0.001)
    assert n.lines[1].start == pytest.approx(n.lines[0].end + 0.15, abs=0.001)
    assert n.duration == pytest.approx(n.lines[-1].end, abs=0.01)
    assert sf.info(n.audio_path).duration == pytest.approx(n.duration, abs=0.01)
    assert [line.text for line in n.lines] == ["Hello there.", "Second line here."]


def test_empty_lines_rejected(tmp_path):
    with pytest.raises(ValueError):
        build_narration([], FakeTTS(), tmp_path / "n.wav", "af_heart")


def test_every_line_uses_the_chosen_voice(tmp_path):
    tts = FakeTTS()
    build_narration(["One.", "Two."], tts, tmp_path / "n.wav", "am_michael")
    assert tts.voices == ["am_michael", "am_michael"]


def test_videos_take_turns_between_the_voices():
    from shorts.voice.narration import voice_for

    voices = ("af_heart", "am_michael")
    assert [voice_for(i, voices) for i in (1, 2, 3, 4)] == ["af_heart", "am_michael", "af_heart", "am_michael"]


def test_a_lead_of_silence_before_the_first_word(tmp_path):
    # the intro whoosh plays over the first moment: words spoken under it were hard to make out
    n = build_narration(["Hello there.", "Two."], FakeTTS(), tmp_path / "n.wav", "af_heart", lead_s=0.4)
    assert n.lines[0].start == pytest.approx(0.4)
    assert n.lines[1].start == pytest.approx(n.lines[0].end + 0.15, abs=0.001)
    audio, rate = sf.read(n.audio_path)
    assert len(audio) / rate == pytest.approx(n.duration, abs=0.01) and n.duration == pytest.approx(n.lines[-1].end)


def test_the_closing_question_is_read_calmly_after_a_longer_pause(tmp_path):
    # read at the lively pace, "Will you buy this new Apple tablet?" sounded rushed
    tts = FakeTTS()
    n = build_narration(["One.", "Two.", "Will you?"], tts, tmp_path / "n.wav", "am_puck",
                        closing_speed=1.0, closing_gap_s=0.4)
    assert tts.speeds == [None, None, 1.0]
    assert n.lines[2].start == pytest.approx(n.lines[1].end + 0.4, abs=0.001)
    assert n.lines[1].start == pytest.approx(n.lines[0].end + 0.15, abs=0.001)


def test_the_sign_off_follows_the_question_after_a_breath(tmp_path):
    # read in one go, "...Apple tablet? Tell us in the comments!" ran the two together
    tts = FakeTTS()
    n = build_narration(["One.", "Would YOU buy it?"], tts, tmp_path / "n.wav", "am_puck", closing_speed=1.0,
                        sign_off="Tell us in the comments!", sign_off_gap_s=0.5)
    assert [line.text for line in n.lines] == ["One.", "Would YOU buy it?", "Tell us in the comments!"]
    assert tts.speeds == [None, 1.0, 1.0]
    assert n.lines[2].start == pytest.approx(n.lines[1].end + 0.5, abs=0.001)
