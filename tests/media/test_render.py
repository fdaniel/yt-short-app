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


def test_the_outro_runs_past_the_narration_with_the_brand_sound(scene, settings, tmp_path):
    from shorts.media import brand
    from shorts.media.sting import write_sting

    work, narration, _, _ = scene
    total = narration.duration + brand.OUTRO_S
    looks = brand.intro(narration.duration) + brand.outro(narration.duration)
    ass = write_ass([CaptionChunk("Hello", 0, narration.duration)], "Footage: Test / Steam", work / "b.ass", brand=looks)
    sting = write_sting(narration.duration, total, work / "sting.wav")
    gray = lavfi_video(tmp_path, "color=c=gray:size=1920x1080:duration=12", name="gray.mp4")
    items = [TimelineItem("shot", total, Shot(gray, 1, 0.5, 0.5 + total, 1.0), None)]
    out = render_video(items, narration, ass, None, work / "video.mp4", settings, sting=sting, duration=total)
    assert probe_video(out).duration == pytest.approx(total, abs=0.1)
    from PIL import Image

    end = Image.open(_frame_file(out, total - 0.15, tmp_path / "end.png")).convert("RGB")
    assert end.getpixel((60, 1500)) == pytest.approx(brand.ORANGE_RGB, abs=12)  # the slash covers the screen
    assert end.getpixel((540, 760)) == pytest.approx(brand.INK_RGB, abs=12)  # the badge, above its letters


def _frame_file(video, seconds, out):
    import subprocess

    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(seconds), "-i", str(video),
                    "-frames:v", "1", str(out)], check=True)
    return out


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
    assert mean(frame, (50, 300, 70, 320)) < 150  # the see-through panel darkens the white footage
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


def test_wide_screenshot_pans_and_fills_the_screen(scene, settings, tmp_path):
    from PIL import Image, ImageDraw

    work, narration, ass, _ = scene
    still = tmp_path / "wide.png"
    image = Image.new("RGB", (3413, 1920), "gray")
    ImageDraw.Draw(image).rectangle((1500, 0, 1900, 1920), fill="white")  # a white column right of centre
    image.save(still)
    out = render_video([TimelineItem("image", 10.0, None, still)], narration, ass, None, work / "v.mp4", settings)
    early, late = frame_at(out, 0.5, tmp_path / "a.png"), frame_at(out, 9.0, tmp_path / "b.png")

    def column(frame):
        return max(range(0, 1080, 20), key=lambda x: mean(frame, (x, 1500, x + 20, 1700)))

    assert column(late) < column(early) - 200  # the picture moved left: the camera pans right
    assert mean(late, (0, 1700, 1080, 1900)) > 60  # no dark bands
