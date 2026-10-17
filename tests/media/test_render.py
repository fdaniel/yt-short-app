import pytest

from shorts.captions import CaptionChunk, write_ass
from shorts.media.cards import render_hook_card
from shorts.media.ffmpeg import probe_video
from shorts.media.render import render_video
from shorts.media.shots import Shot
from shorts.media.timeline import TimelineItem
from tests.helpers import fake_narration, lavfi_video, sine_mp3


@pytest.fixture
def scene(tmp_path, font_file, synthetic_video):
    work = tmp_path / "it's a dir: with spaces"
    work.mkdir()
    narration = fake_narration(work, seconds=10)
    ass = write_ass([CaptionChunk("Hello {there}", 0, 10)], "Footage: Test / Steam", work / "c.ass")
    card = render_hook_card("DLSS 5 is here", work / "card.png", font_file)
    left_subject = lavfi_video(
        tmp_path, "color=c=black:size=1920x1080:duration=6,drawbox=x=150:y=300:w=300:h=400:color=white:t=fill",
        name="left.mp4",
    )
    items = [
        TimelineItem("shot", 3.3, Shot(synthetic_video, 1, 0.5, 3.8, 1.0), None),
        TimelineItem("image", 3.3, None, card),
        TimelineItem("shot", 3.4, Shot(left_subject, 2, 1.0, 4.4, 1.0), None),
    ]
    return work, narration, ass, items


def test_render_mixed_timeline(scene, settings):
    work, narration, ass, items = scene
    out = render_video(items, narration, ass, None, work / "video.mp4", settings)
    info = probe_video(out)
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio and info.duration == pytest.approx(10, abs=0.2)
    assert out.stat().st_size < 50 * 1024 * 1024
    assert not (work / "segments").exists()


def test_render_with_looping_music(scene, settings, tmp_path):
    work, narration, ass, items = scene
    music = sine_mp3(tmp_path / "music.mp3", seconds=3)
    out = render_video(items, narration, ass, music, work / "video.mp4", settings)
    assert probe_video(out).duration == pytest.approx(10, abs=0.2)
