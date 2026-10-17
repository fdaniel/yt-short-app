"""Cheap, deterministic checks that run before any LLM fact check."""

import re

from shorts.config import VideoSettings
from shorts.script.schema import ScriptDraft

_NUMBER = re.compile(r"\d[\d,.]*\d|\d")


def narration_lines(draft: ScriptDraft) -> list[str]:
    return [draft.hook, *draft.body, draft.closing]


def word_count(draft: ScriptDraft) -> int:
    return sum(len(line.split()) for line in narration_lines(draft))


def length_problems(draft: ScriptDraft, video: VideoSettings) -> list[str]:
    words = word_count(draft)
    if words < video.min_words:
        return [f"narration too short: {words} words (minimum {video.min_words})"]
    if words > video.max_words:
        return [f"narration too long: {words} words (maximum {video.max_words})"]
    return []


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def quotes_missing(draft: ScriptDraft, source_text: str) -> list[str]:
    source = _normalise(source_text)
    return [c.source_quote for c in draft.claims if _normalise(c.source_quote) not in source]


def _numbers(text: str) -> list[str]:
    return [match.replace(",", "") for match in _NUMBER.findall(text)]


def numbers_ungrounded(draft: ScriptDraft, source_text: str) -> list[str]:
    """Numbers said in the narration that never appear in the source."""
    known = set(_numbers(source_text))
    spoken = _numbers(" ".join(narration_lines(draft)))
    return list(dict.fromkeys(n for n in spoken if n not in known))
