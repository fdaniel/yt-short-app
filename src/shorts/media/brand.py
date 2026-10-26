"""The Loadout Daily look, drawn in the caption layer: the orange slash, the LD badge, the outro.

One idea carries the brand: an orange slash. It sweeps in over the first frames (no intro
before the action: an intro the viewer has to sit through gets swiped) and closes the video
on the badge, so the Short's loop runs slash into slash. In between, only the badge: clips
change every few seconds, and a flick on each cut was too much.
"""

from dataclasses import dataclass

ORANGE_RGB = (244, 81, 30)  # #F4511E, the LD mark on the channel and the dashboard
INK_RGB = (26, 33, 40)  # #1A2128


def ass_colour(rgb: tuple[int, int, int]) -> str:
    """ASS writes colours blue first: &H00BBGGRR&."""
    red, green, blue = rgb
    return f"&H00{blue:02X}{green:02X}{red:02X}&"


ORANGE = ass_colour(ORANGE_RGB)
INK = ass_colour(INK_RGB)
OUTRO_S = 0.9  # the badge holds after the last word, then the loop starts again

BADGE = (104, 176, 46)  # centre x, centre y, radius: top left, clear of the Shorts buttons
_INTRO_SWEEP_MS = 380
# \\an5 centres Anton's whole line box, which leaves capitals this share of the size below centre
_CAP_DROP = 0.055


@dataclass(frozen=True)
class BrandEvent:
    start: float
    end: float
    style: str
    text: str
    layer: int = 5


def _circle(r: int) -> str:
    """A circle from four bezier quarters (ASS has no circle command), drawn inside 0..2r so \\an5 centres it."""
    k = round(r * 0.5523)
    return (f"m {r} 0 b {r + k} 0 {2 * r} {r - k} {2 * r} {r} b {2 * r} {r + k} {r + k} {2 * r} {r} {2 * r} "
            f"b {r - k} {2 * r} 0 {r + k} 0 {r} b 0 {r - k} {r - k} 0 {r} 0")


def _slash(width: int, lean: int = 420) -> str:
    """A band leaning right, full screen height, its top-left corner at 0,0."""
    return f"m {lean} 0 l {lean + width} 0 l {width} 1920 l 0 1920"


def _shape(colour: str, drawing: str, tags: str = "", align: int = 7) -> str:
    """A filled drawing; \\an7 places its top-left corner, \\an5 its centre (and scales around it)."""
    return f"{{\\an{align}\\bord0\\shad0\\1c{colour}{tags}\\p1}}{drawing}{{\\p0}}"


def _sweep(start: float, ms: int, width: int, colour: str, delay_ms: int = 0) -> BrandEvent:
    """One band crossing the screen left to right in `ms`."""
    begin = -width - 420
    tags = f"\\move({begin},0,1080,0,{delay_ms},{delay_ms + ms})"
    return BrandEvent(start, start + (delay_ms + ms) / 1000, "Brand", _shape(colour, _slash(width), tags))


def _cap_centre(y: int, size: int) -> int:
    """The position that puts the middle of Anton capitals of this size on y."""
    return y - round(size * _CAP_DROP)


def _badge(start: float, end: float, *, pop: bool) -> list[BrandEvent]:
    x, y, r = BADGE
    grow = "\\fscx0\\fscy0\\t(0,140,\\fscx118\\fscy118)\\t(140,240,\\fscx100\\fscy100)" if pop else ""
    disc = _shape(ORANGE, _circle(r), f"\\pos({x},{y}){grow}", align=5)
    letters = f"{{\\an5\\pos({x},{_cap_centre(y, 50)}){grow}\\fs50\\bord0\\shad0}}LD"
    return [BrandEvent(start, end, "Brand", disc), BrandEvent(start, end, "Brand", letters, layer=6)]


def _wordmark(start: float, end: float) -> BrandEvent:
    """LOADOUT DAILY slides out of the badge, holds, and slides back in."""
    x, y, r = BADGE
    left, right = x + r + 14, 760
    hold_ms = round((end - start) * 1000)
    clip = (f"\\clip({left},{y - 40},{left},{y + 40})\\t(120,420,\\clip({left},{y - 40},{right},{y + 40}))"
            f"\\t({hold_ms - 300},{hold_ms},\\clip({left},{y - 40},{left},{y + 40}))")
    return BrandEvent(start, end, "Brand", f"{{\\an4\\pos({left},{y + 2}){clip}\\fs62\\bord4\\shad0}}LOADOUT DAILY")


def intro(narration_s: float) -> list[BrandEvent]:
    """Over the first frames: the slash sweeps through, the badge pops, the name flashes by."""
    events = [_sweep(0.0, _INTRO_SWEEP_MS, 300, ORANGE), _sweep(0.0, _INTRO_SWEEP_MS, 70, INK, delay_ms=60)]
    events += _badge(0.15, narration_s, pop=True)
    events.append(_wordmark(0.15, 2.1))
    return events


def outro(narration_s: float) -> list[BrandEvent]:
    """After the last word: the slash covers the screen and leaves the badge, big, in the middle."""
    start, end = narration_s, narration_s + OUTRO_S
    pop = "\\fscx0\\fscy0\\t(160,300,\\fscx112\\fscy112)\\t(300,380,\\fscx100\\fscy100)"
    x, y, r, size = 540, 880, 150, 150

    def fade_in(top: int, size: int, ms: int, text: str) -> str:
        return f"{{\\an8\\pos({x},{top})\\alpha&HFF&\\t({ms},{ms + 160},\\alpha&H00&)\\fs{size}\\bord0\\shad0\\1c{INK}}}{text}"

    shapes = [
        (7, _shape(ORANGE, _slash(1600), "\\move(-2100,0,-480,0,0,220)")),
        (8, _shape(INK, _circle(r), f"\\pos({x},{y}){pop}", align=5)),
        (9, f"{{\\an5\\pos({x},{_cap_centre(y, size)}){pop}\\fs{size}\\bord0\\shad0}}LD"),
        (9, fade_in(1070, 96, 260, "LOADOUT DAILY")),
        (9, fade_in(1180, 50, 340, "TECH & GAMING NEWS, DAILY")),
    ]
    return [BrandEvent(start, end, "Brand", text, layer) for layer, text in shapes]
