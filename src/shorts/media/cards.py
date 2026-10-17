"""Generated 1080x1920 visuals: hook card, fact card, and screenshot stills."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from shorts.script.schema import CardFact

CANVAS = (1080, 1920)
SAFE_BOX = (80, 250, 900, 1350)  # left, top, right, bottom: clear of the Shorts UI
BACKGROUND = (11, 15, 20)
ACCENT = (61, 220, 151)
TEXT = (245, 247, 250)
MUTED = (150, 160, 175)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        candidate = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(candidate, font=font) <= width:
            lines[-1] = candidate
        else:
            lines.append(word)
    return lines


def _fit(draw, text, font_file: Path, width: int, height: int, size: int, minimum: int = 36):
    """Largest font size (down to `minimum`) at which `text` wraps inside width x height."""
    while True:
        font = ImageFont.truetype(str(font_file), size)
        lines = _wrap(draw, text, font, width)
        line_h = int(size * 1.2)
        if (len(lines) * line_h <= height and all(draw.textlength(l, font=font) <= width for l in lines)) or size <= minimum:
            return font, lines[: max(1, height // line_h)], line_h
        size -= 4


def _blank() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", CANVAS, BACKGROUND)
    return image, ImageDraw.Draw(image)


def render_hook_card(text: str, out: Path, font_file: Path) -> Path:
    image, draw = _blank()
    left, top, right, bottom = SAFE_BOX
    draw.rectangle((left, top, left + 120, top + 14), fill=ACCENT)
    font, lines, line_h = _fit(draw, text, font_file, right - left, bottom - top - 80, 110)
    y = top + 80
    for line in lines:
        draw.text((left, y), line, font=font, fill=TEXT)
        y += line_h
    image.save(out)
    return out


def render_fact_card(title: str, facts: list[CardFact], out: Path, font_file: Path) -> Path:
    if not facts:
        raise ValueError("a fact card needs at least one fact")
    image, draw = _blank()
    left, top, right, bottom = SAFE_BOX
    title_font, title_lines, title_h = _fit(draw, title, font_file, right - left, 200, 84)
    y = top
    for line in title_lines:
        draw.text((left, y), line, font=title_font, fill=ACCENT)
        y += title_h
    row_h = (bottom - y - 40) // len(facts)
    for fact in facts:
        label_font, label_lines, _ = _fit(draw, fact.label.upper(), font_file, right - left, row_h // 3, 40, 24)
        value_font, value_lines, _ = _fit(draw, fact.value, font_file, right - left, row_h // 2, 72, 32)
        draw.text((left, y + 40), label_lines[0], font=label_font, fill=MUTED)
        draw.text((left, y + 40 + row_h // 3), value_lines[0], font=value_font, fill=TEXT)
        y += row_h
    image.save(out)
    return out


def render_still(image: Path, out: Path) -> Path:
    with Image.open(image) as src:
        src = src.convert("RGB")
        cover_scale = max(CANVAS[0] / src.width, CANVAS[1] / src.height)
        background = src.resize((round(src.width * cover_scale), round(src.height * cover_scale)))
        left = (background.width - CANVAS[0]) // 2
        top = (background.height - CANVAS[1]) // 2
        background = background.crop((left, top, left + CANVAS[0], top + CANVAS[1]))
        background = background.filter(ImageFilter.GaussianBlur(30)).point(lambda v: int(v * 0.45))
        fit_scale = CANVAS[0] / src.width
        foreground = src.resize((CANVAS[0], round(src.height * fit_scale)))
        background.paste(foreground, (0, (CANVAS[1] - foreground.height) // 2 - 200))
    background.save(out)
    return out
