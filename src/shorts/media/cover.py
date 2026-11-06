"""The video's cover image: a frame of its footage with two or three big words in the Loadout Daily look."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from shorts.media.brand import ORANGE_RGB
from shorts.media.crop import CropMode, CropPlan, choose_crop
from shorts.media.ffmpeg import run_ffmpeg
from shorts.media.shots import Shot

ANTON = Path(__file__).parents[3] / "assets" / "fonts" / "Anton-Regular.ttf"
SIZE = (1080, 1920)
TEXT_WIDTH = 960
START_SIZE, MIN_SIZE, SIZE_STEP = 300, 80, 6
FIRST_LINE_Y = 420
LINE_GAP = 30
OUTLINE = 14
DIM = 0.8  # the picture a little darker, so white words stand out
FRAME_TIMEOUT_S = 120


def fit_size(text: str, font: Path, max_width: int) -> int:
    """The biggest font size, from START_SIZE down, at which `text` fits in `max_width` pixels."""
    size = START_SIZE
    while size > MIN_SIZE and ImageFont.truetype(str(font), size).getlength(text) > max_width:
        size -= SIZE_STEP
    return size


def cover_frame(shot: Shot, out: Path, *, timeout_s: int = FRAME_TIMEOUT_S) -> Path:
    """One frame from the middle of the clip, cropped to the centre 9:16 like the video shows it."""
    found = choose_crop(shot.source, shot.start, shot.end)
    plan = CropPlan(CropMode.CENTER, top=found.top, height=found.height)
    bars = f"crop=iw:{plan.height}:0:{plan.top}," if plan.height else ""
    at = (shot.start + shot.end) / 2
    run_ffmpeg(["-ss", f"{at:.3f}", "-i", str(shot.source), "-frames:v", "1", "-vf",
                f"{bars}scale={SIZE[0]}:{SIZE[1]}:force_original_aspect_ratio=increase,crop={SIZE[0]}:{SIZE[1]}",
                str(out)], timeout_s=timeout_s)
    return out


def render_cover(picture: Path, lines: list[str], out: Path, font: Path = ANTON) -> Path:
    """Big outlined words over the picture: white, with the second line in the channel's orange."""
    with Image.open(picture) as source:
        image = ImageEnhance.Brightness(source.convert("RGB").resize(SIZE)).enhance(DIM)
    draw = ImageDraw.Draw(image)
    y = FIRST_LINE_Y
    for index, text in enumerate(lines):
        size = fit_size(text, font, TEXT_WIDTH)
        colour = ORANGE_RGB if index == 1 else (255, 255, 255)
        draw.text((SIZE[0] // 2, y), text, font=ImageFont.truetype(str(font), size), fill=colour, anchor="ma",
                  stroke_width=OUTLINE, stroke_fill=(0, 0, 0))
        y += size + LINE_GAP
    image.save(out)
    return out
