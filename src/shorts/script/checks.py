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
    # say how far off it is: told only the limit, a model rewrites to about the same length
    if words < video.min_words:
        return [f"narration too short: {words} words (minimum {video.min_words}): "
                f"add at least {video.min_words - words} words of facts from the SOURCE"]
    if words > video.max_words:
        return [f"narration too long: {words} words (maximum {video.max_words}): "
                f"cut at least {words - video.max_words} words, e.g. shorten or drop a body sentence"]
    return []


def _normalise(text: str) -> str:
    return " ".join(text.translate(_TYPOGRAPHY).lower().split())


_ELLIPSIS = re.compile(r"\.\.\.|\u2026")


def _quoted(quote: str, source: str) -> bool:
    """Verbatim, where a quote shortened with "..." counts when every part is verbatim, in order."""
    position = 0
    for part in (_normalise(p) for p in _ELLIPSIS.split(quote)):
        if not part:
            continue
        found = source.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return position > 0


def quotes_missing(draft: ScriptDraft, source_text: str) -> list[str]:
    source = _normalise(source_text)
    return [c.source_quote for c in draft.claims if not _quoted(c.source_quote, source)]


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


_FILLER = re.compile(r"\b(news flash|breaking news|in other news)\b|^\s*breaking\b", re.IGNORECASE)
_OUT_NOW = re.compile(r"\b(out now|available now|now available|now live|is live|available today|out today"
                      r"|launches today|has launched|is here)\b", re.IGNORECASE)
_STOP_WORDS = frozenset("""the a an and or of to in on for with is are was were be been it its this that these those
you your can will now at by from as has have had new more than into over upon their they them our we all any also
just which who what when where how about after before up out not but so if then there here since one two three""".split())
# a body line repeats the hook when it reuses at least this many of the hook's words, and this share of them
MIN_SHARED_WORDS = 3
MIN_SHARED_SHARE = 0.6


def _bare(word: str) -> str:
    return word.strip(".,!?:;\"'()")


def _content_words(line: str) -> set[str]:
    """Plain words that carry meaning: no names (capitalised), numbers or small words; plural 's' dropped."""
    words = set()
    for word in map(_bare, line.split()):
        if not word or word[0].isupper() or any(ch.isdigit() for ch in word):
            continue
        word = word.lower()
        if word not in _STOP_WORDS and len(word) > 2:
            words.add(word[:-1] if word.endswith("s") and len(word) > 3 else word)
    return words


def _names(line: str) -> set[str]:
    """Capitalised words after the first (which is capitalised anyway): the game, product or company."""
    return {_bare(word) for word in line.split()[1:] if word[:1].isupper()} - {"The", "A"}


def repetition_problems(draft: ScriptDraft) -> list[str]:
    """A Short has no time to say anything twice: filler labels, "out now" twice, a body line restating the hook."""
    lines = narration_lines(draft)
    problems = [f"filler label {match.group(0).strip()!r} in the narration: start with the news itself"
                for line in lines if (match := _FILLER.search(line))]
    out_now = [line for line in lines if _OUT_NOW.search(line)]
    problems += [f"says twice that it is out or available ({first!r} / {second!r}): say it once, add a new fact instead"
                 for i, first in enumerate(out_now) for second in out_now[i + 1:] if _names(first) & _names(second)]
    hook = _content_words(lines[0])
    for line in lines[1:]:
        shared = hook & _content_words(line)
        if len(shared) >= MIN_SHARED_WORDS and len(shared) >= MIN_SHARED_SHARE * len(hook):
            problems.append(f"repeats the hook ({lines[0]!r} / {line!r}): every sentence must add a new fact")
    return problems
