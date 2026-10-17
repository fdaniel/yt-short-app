"""Short, timed caption chunks rendered as an ASS subtitle file."""

import re
from dataclasses import dataclass
from pathlib import Path

from shorts.voice.narration import Narration

_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,6,0,2,120,200,700,1
Style: Credit,{font},34,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,3,0,7,60,60,120,1

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
    cleaned = "".join(ch for ch in text if ch not in "{}\\" and ord(ch) <= 0xFFFF)
    return re.sub(r"\s+", " ", cleaned).strip()


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


def _dialogue(style: str, start: float, end: float, text: str) -> str:
    return f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{sanitize_caption_text(text)}"


def write_ass(chunks: list[CaptionChunk], credit_text: str, out_path: Path, font_name: str = "DejaVu Sans") -> Path:
    end = max((c.end for c in chunks), default=0.0)
    events = [_dialogue("Credit", 0.0, end, credit_text)]
    events += [_dialogue("Caption", c.start, c.end, c.text) for c in chunks]
    out_path.write_text(_HEADER.format(font=font_name) + "\n".join(events) + "\n", encoding="utf-8")
    return out_path
