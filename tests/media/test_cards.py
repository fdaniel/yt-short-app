import pytest
from PIL import Image

from shorts.media.cards import CANVAS, render_fact_card, render_hook_card, render_still
from shorts.script.schema import CardFact


def test_hook_card_canvas_sized_even_with_long_text(tmp_path, font_file):
    hook = render_hook_card("NVIDIA just announced DLSS 5 " * 8, tmp_path / "h.png", font_file)
    assert Image.open(hook).size == CANVAS


def test_fact_card_canvas_sized(tmp_path, font_file):
    facts = [CardFact(label="Price", value="$1,999"), CardFact(label="Memory", value="32GB GDDR7")]
    out = render_fact_card("RTX 5090", facts, tmp_path / "f.png", font_file)
    assert Image.open(out).size == CANVAS


def test_fact_card_needs_facts(tmp_path, font_file):
    with pytest.raises(ValueError):
        render_fact_card("x", [], tmp_path / "f.png", font_file)


def test_still_fits_canvas(tmp_path):
    src = tmp_path / "s.jpg"
    Image.new("RGB", (1920, 1080), "red").save(src)
    assert Image.open(render_still(src, tmp_path / "o.png")).size == CANVAS


def test_text_stays_in_safe_zone(tmp_path, font_file):
    out = render_hook_card("WOW " * 40, tmp_path / "h.png", font_file)
    img = Image.open(out).convert("L")
    bottom_band = img.crop((0, 1400, 1080, 1920))
    assert bottom_band.getextrema()[1] < 80  # nothing bright drawn under the Shorts UI
