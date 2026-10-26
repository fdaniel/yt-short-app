"""Short, timed caption chunks rendered as an ASS subtitle file."""

from dataclasses import dataclass
from pathlib import Path

from shorts.media.brand import ORANGE, BrandEvent
from shorts.text import clean_text
from shorts.voice.narration import Narration

CAPTION_SIZE = 104
BRAND_FONT = "Anton"
_POP = "\\fscx84\\fscy84\\t(0,90,\\fscx100\\fscy100)"  # each new phrase pops in
CAPTION_MARGIN_V = 520  # bottom edge at y=1400: under card text, above the Shorts title/buttons

_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,7,0,2,90,90,{margin_v},1
Style: Credit,DejaVu Sans,30,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,3,0,7,62,60,240,1
Style: Brand,{font},60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,1,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


@dataclass(frozen=True)
class CaptionChunk:
    text: str
    start: float
    end: float


def sanitize_caption_text(text: str) -> str:
    """Drop characters that ASS treats as markup, and emoji the font cannot draw."""
    return clean_text(text)


def _group_words(text: str, max_chars: int, max_words: int) -> list[str]:
    groups: list[list[str]] = []
    for word in text.split():
        current = groups[-1] if groups else None
        if current and len(current) < max_words and len(" ".join([*current, word])) <= max_chars:
            current.append(word)
        else:
            groups.append([word])
    return [" ".join(g) for g in groups]


def chunk_captions(narration: Narration, max_chars: int = 28, max_words: int = 4) -> list[CaptionChunk]:
    chunks: list[CaptionChunk] = []
    for line in narration.lines:
        groups = _group_words(sanitize_caption_text(line.text), max_chars, max_words)
        total_chars = sum(len(g) for g in groups) or 1
        cursor = line.start
        for i, group in enumerate(groups):
            is_last = i == len(groups) - 1
            end = line.end if is_last else cursor + (line.end - line.start) * len(group) / total_chars
            chunks.append(CaptionChunk(text=group, start=cursor, end=end))
            cursor = end
    return chunks


def _ass_time(seconds: float) -> str:
    centis = int(round(seconds * 100))
    hours, rest = divmod(centis, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _event(style: str, start: float, end: float, text: str, layer: int = 0) -> str:
    return f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{text}"


def _dialogue(style: str, start: float, end: float, text: str) -> str:
    return _event(style, start, end, sanitize_caption_text(text))


def _spoken_word_events(chunk: CaptionChunk) -> list[str]:
    """The phrase stays on screen; the word being said turns orange (timed by its share of the letters)."""
    words = sanitize_caption_text(chunk.text).upper().split()
    total = sum(len(w) for w in words) or 1
    events, cursor = [], chunk.start
    for i, word in enumerate(words):
        end = chunk.end if i == len(words) - 1 else cursor + (chunk.end - chunk.start) * len(word) / total
        lit = " ".join(f"{{\\1c{ORANGE}}}{w}{{\\1c&H00FFFFFF&}}" if j == i else w for j, w in enumerate(words))
        events.append(_event("Caption", cursor, end, (f"{{{_POP}}}" if i == 0 else "") + lit))
        cursor = end
    return events


def write_ass(
    chunks: list[CaptionChunk], credit_text: str, out_path: Path, font_name: str = BRAND_FONT,
    brand: list[BrandEvent] | None = None,
) -> Path:
    end = max((c.end for c in chunks), default=0.0)
    events = [_dialogue("Credit", 0.0, end, credit_text)]
    events += [e for c in chunks for e in _spoken_word_events(c)]
    events += [_event(b.style, b.start, b.end, b.text, b.layer) for b in brand or []]
    out_path.write_text(_HEADER.format(font=font_name, size=CAPTION_SIZE, margin_v=CAPTION_MARGIN_V) + "\n".join(events) + "\n", encoding="utf-8")
    return out_path
