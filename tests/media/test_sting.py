import numpy as np
import soundfile as sf

from shorts.media.sting import RATE, write_sting


def _loudness(track: np.ndarray, start_s: float, end_s: float) -> float:
    return float(np.abs(track[int(start_s * RATE):int(end_s * RATE)]).max())


def test_the_sound_track_is_as_long_as_the_video_and_clean(tmp_path):
    out = write_sting(20.0, 20.9, tmp_path / "sting.wav")
    track, rate = sf.read(out)
    assert rate == RATE
    assert abs(len(track) / rate - 20.9) < 0.01
    assert np.isfinite(track).all() and np.abs(track).max() <= 1.0


def test_whoosh_at_the_start_chime_after_the_last_word_quiet_between(tmp_path):
    track, _ = sf.read(write_sting(20.0, 20.9, tmp_path / "sting.wav"))
    assert _loudness(track, 0.0, 0.45) > 0.1
    assert _loudness(track, 20.15, 20.7) > 0.1  # the chime
    assert _loudness(track, 2.0, 19.0) == 0.0  # the narration is never covered


def test_the_same_sound_every_video(tmp_path):
    first, _ = sf.read(write_sting(20.0, 20.9, tmp_path / "a.wav"))
    second, _ = sf.read(write_sting(20.0, 20.9, tmp_path / "b.wav"))
    assert np.array_equal(first, second)
