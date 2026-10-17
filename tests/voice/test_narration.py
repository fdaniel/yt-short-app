import pytest
import soundfile as sf

from shorts.voice.narration import build_narration
from tests.fakes import FakeTTS


def test_narration_timing(tmp_path):
    n = build_narration(["Hello there.", "Second line here."], FakeTTS(), tmp_path / "n.wav")
    assert n.lines[0].start == 0
    assert n.lines[0].end == pytest.approx(len("Hello there.") * 0.05, abs=0.001)
    assert n.lines[1].start == pytest.approx(n.lines[0].end + 0.15, abs=0.001)
    assert n.duration == pytest.approx(n.lines[-1].end, abs=0.01)
    assert sf.info(n.audio_path).duration == pytest.approx(n.duration, abs=0.01)
    assert [line.text for line in n.lines] == ["Hello there.", "Second line here."]


def test_empty_lines_rejected(tmp_path):
    with pytest.raises(ValueError):
        build_narration([], FakeTTS(), tmp_path / "n.wav")
