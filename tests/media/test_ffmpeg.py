import pytest

from shorts.media.ffmpeg import FFmpegError, probe_video, run_ffmpeg, strip_audio


def test_probe_synthetic(synthetic_video):
    info = probe_video(synthetic_video)
    assert (info.width, info.height) == (1920, 1080)
    assert info.has_audio and abs(info.duration - 6) < 0.2


def test_strip_audio(synthetic_video, tmp_path):
    out = strip_audio(synthetic_video, tmp_path / "noaudio.mp4", timeout_s=60)
    assert probe_video(out).has_audio is False


def test_bad_args_raise_with_stderr(tmp_path):
    with pytest.raises(FFmpegError, match="No such file"):
        run_ffmpeg(["-i", str(tmp_path / "missing.mp4"), str(tmp_path / "o.mp4")], timeout_s=30)


def test_timeout_raises(tmp_path):
    with pytest.raises(FFmpegError, match="timed out"):
        run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=duration=600", "-f", "null", "-"], timeout_s=1)


def test_probe_missing_file_raises(tmp_path):
    with pytest.raises(FFmpegError):
        probe_video(tmp_path / "missing.mp4")
