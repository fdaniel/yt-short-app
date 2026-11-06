import pytest
from PIL import Image

from shorts.media.brand import ORANGE_RGB
from shorts.media.cover import ANTON, cover_frame, fit_size, render_cover
from shorts.media.shots import Shot


@pytest.fixture
def frame(tmp_path):
    path = tmp_path / "frame.png"
    Image.new("RGB", (1080, 1920), (40, 60, 80)).save(path)
    return path


def test_a_long_line_gets_a_smaller_size_to_fit():
    assert fit_size("REVOLVERS", ANTON, 960) < fit_size("APEX", ANTON, 960)


def test_cover_is_vertical_with_the_middle_line_in_orange(frame, tmp_path):
    out = render_cover(frame, ["DUAL", "REVOLVERS", "IN APEX"], tmp_path / "cover.png")
    image = Image.open(out).convert("RGB")
    assert image.size == (1080, 1920)
    colours = image.getcolors(1080 * 1920)
    orange = sum(n for n, rgb in colours if all(abs(a - b) < 30 for a, b in zip(rgb, ORANGE_RGB)))
    assert orange > 20_000


def test_cover_frame_comes_from_the_centre_of_the_clip(synthetic_video, tmp_path):
    out = cover_frame(Shot(synthetic_video, 1, 0.5, 3.5, 1.0), tmp_path / "f.png")
    assert Image.open(out).size == (1080, 1920)
