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


def test_long_fact_value_is_not_cut_to_one_line(tmp_path, font_file):
    # a real run showed "ASUS, Dell, HP," for "ASUS, Dell, HP, Lenovo, Microsoft, MSI"
    facts = [CardFact(label="Partners", value="ASUS, Dell, HP, Lenovo, Microsoft, MSI and Razer")]
    image = Image.open(render_fact_card("RTX Spark", facts, tmp_path / "f.png", font_file)).convert("L")
    body = image.crop((0, 450, image.width, 1080)).point(lambda v: 255 if v > 230 else 0)
    top, bottom = body.getbbox()[1], body.getbbox()[3]
    assert bottom - top > 120  # more than one line of value text


def _assert_see_through_panel(path):
    image = Image.open(path)
    assert image.mode == "RGBA" and image.size == CANVAS
    alpha = image.getchannel("A")
    assert alpha.getpixel((5, 5)) == 0 and alpha.getpixel((540, 1800)) == 0  # footage shows around the panel
    assert 150 <= alpha.getpixel((60, 300)) < 255  # a dark, slightly see-through panel behind the text
    assert alpha.getextrema()[1] == 255  # the text itself is solid


def test_hook_overlay_is_a_panel_over_the_footage(tmp_path, font_file):
    _assert_see_through_panel(render_hook_card("DLSS 5 is here", tmp_path / "h.png", font_file, overlay=True))


def test_fact_overlay_is_a_panel_over_the_footage(tmp_path, font_file):
    facts = [CardFact(label="Price", value="$1,999")]
    _assert_see_through_panel(render_fact_card("RTX 5090", facts, tmp_path / "f.png", font_file, overlay=True))


def test_full_card_stays_opaque(tmp_path, font_file):
    image = Image.open(render_hook_card("DLSS 5 is here", tmp_path / "h.png", font_file))
    assert image.mode == "RGB" and image.getpixel((5, 5)) == (11, 15, 20)
