import pytest

from shorts.clips.moments import Moment
from shorts.clips.render import grab_frames, render_clip, write_clip_ass
from shorts.media.ffmpeg import probe_video

from tests.clips.helpers import clip_text, gameplay


def test_the_captions_show_the_hook_on_top_and_lines_after_it(tmp_path):
    ass = write_clip_ass(clip_text(), 30.0, tmp_path / "clip.ass").read_text()
    assert "BOSS DOWN IN ONE COMBO" in ass and "Hook" in ass
    assert "DODGE FIRST" in ass and "THEN THE HEAVY HIT" in ass


def test_a_landscape_clip_becomes_a_vertical_short_with_its_own_sound(tmp_path, settings):
    source = gameplay(tmp_path / "in", seconds=8)
    ass = write_clip_ass(clip_text(), 6.0, tmp_path / "clip.ass")
    out = render_clip(source, Moment(1.0, 7.0, 0.0), ass, tmp_path / "video.mp4", settings)
    info = probe_video(out)
    assert (info.width, info.height, info.has_audio) == (1080, 1920, True)
    assert info.duration == pytest.approx(6.0, abs=0.3)


def test_a_vertical_clip_is_kept_vertical(tmp_path, settings):
    source = gameplay(tmp_path / "in", seconds=4, size="720x1280")
    ass = write_clip_ass(clip_text(), 3.0, tmp_path / "clip.ass")
    info = probe_video(render_clip(source, Moment(0.0, 3.0, 0.0), ass, tmp_path / "v.mp4", settings))
    assert (info.width, info.height) == (1080, 1920)


def test_frames_are_taken_from_the_moment_for_the_writer(tmp_path):
    frames = grab_frames(gameplay(tmp_path / "in", seconds=8), Moment(2.0, 6.0, 0.0), tmp_path, count=3)
    assert len(frames) == 3 and all(f.read_bytes()[:2] == b"\xff\xd8" for f in frames)  # JPEG


def test_long_clips_may_be_bigger_files_than_news_videos(tmp_path, settings):
    from shorts.clips.render import output_limit_mb

    assert output_limit_mb(settings) > settings.video.max_output_mb
