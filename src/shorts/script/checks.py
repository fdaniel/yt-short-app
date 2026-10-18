"""Cheap, deterministic checks that run before any LLM fact check."""

import re

from shorts.config import VideoSettings
from shorts.script.schema import ScriptDraft
from shorts.text import clean_text

_NUMBER = re.compile(r"\d[\d,.]*\d|\d")
_TYPOGRAPHY = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                             "\u2013": "-", "\u2014": "-", "\u00a0": " "})


def narration_lines(draft: ScriptDraft) -> list[str]:
    return [clean_text(line) for line in (draft.hook, *draft.body, draft.closing)]


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
    return " ".join(text.translate(_TYPOGRAPHY).lower().split())


def quotes_missing(draft: ScriptDraft, source_text: str) -> list[str]:
    source = _normalise(source_text)
    return [c.source_quote for c in draft.claims if _normalise(c.source_quote) not in source]


def _numbers(text: str) -> list[str]:
    return [match.replace(",", "") for match in _NUMBER.findall(text)]


def numbers_ungrounded(draft: ScriptDraft, source_text: str) -> list[str]:
    """Numbers said in the narration or shown on cards that never appear in the source."""
    known = set(_numbers(source_text))
    on_cards = [f"{fact.label} {fact.value}" for fact in draft.card_facts]
    spoken = _numbers(" ".join(narration_lines(draft) + on_cards))
    return list(dict.fromkeys(n for n in spoken if n not in known))


MIN_CARD_FACTS = 2


def card_problems(draft: ScriptDraft) -> list[str]:
    if len(draft.card_facts) < MIN_CARD_FACTS:
        return [f"card_facts has {len(draft.card_facts)} entries; give {MIN_CARD_FACTS} to 6 from the SOURCE"]
    return []
