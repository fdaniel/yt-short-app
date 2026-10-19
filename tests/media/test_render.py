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


def frame_at(video, seconds, out):
    import subprocess

    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(seconds), "-i", str(video),
                    "-frames:v", "1", str(out)], check=True)
    from PIL import Image

    return Image.open(out).convert("L")


def test_letterboxed_trailer_fills_the_frame(scene, settings, tmp_path):
    work, narration, ass, _ = scene
    boxed = lavfi_video(
        tmp_path, "color=c=gray:size=1920x810:duration=12,pad=1920:1080:0:135:black", name="boxed.mp4"
    )
    items = [TimelineItem("shot", 10.0, Shot(boxed, 1, 0.5, 10.5, 1.0), None)]
    out = render_video(items, narration, ass, None, work / "video.mp4", settings)
    frame = frame_at(out, 5, tmp_path / "f.png")
    for band in ((0, 100, 1080, 230), (0, 1700, 1080, 1900)):  # where the bars used to be
        assert mean(frame, band) > 60


def mean(frame, box):
    import numpy as np

    return float(np.asarray(frame.crop(box)).mean())


def test_text_panel_is_drawn_over_the_footage(scene, settings, tmp_path, font_file):
    work, narration, ass, _ = scene
    white = lavfi_video(tmp_path, "color=c=white:size=1920x1080:duration=12", name="white.mp4")
    overlay = render_hook_card("DLSS 5 is here", work / "hook_overlay.png", font_file, overlay=True)
    items = [TimelineItem("shot", 10.0, Shot(white, 1, 0.5, 10.5, 1.0), None, overlay)]
    frame = frame_at(render_video(items, narration, ass, None, work / "video.mp4", settings), 5, tmp_path / "f.png")
    assert mean(frame, (50, 240, 70, 260)) < 100  # the dark panel
    assert mean(frame, (0, 1700, 1080, 1900)) > 200  # footage around it


def test_screenshots_move(scene, settings, tmp_path):
    from PIL import Image, ImageDraw

    work, narration, ass, _ = scene
    still = tmp_path / "still.png"
    image = Image.new("RGB", (1080, 1920), "gray")
    ImageDraw.Draw(image).rectangle((300, 600, 780, 1300), fill="white")
    image.save(still)
    out = render_video([TimelineItem("image", 10.0, None, still)], narration, ass, None, work / "v.mp4", settings)
    early, late = frame_at(out, 0.5, tmp_path / "a.png"), frame_at(out, 9.0, tmp_path / "b.png")
    # a slow zoom: the white box grows, so the row just above it turns white
    assert mean(late, (400, 560, 680, 590)) > mean(early, (400, 560, 680, 590)) + 40
