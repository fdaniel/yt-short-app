"""Lay out visuals over the narration while enforcing the trailer limits (pure, no I/O)."""

from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path
from typing import Literal

from shorts.media.shots import Shot


_EPSILON = 1e-6  # clips cut to exactly one slot can come out a hair short in floating point
ADJACENT_S = 0.15  # scenes this close are back to back: the trailer's own cut, nothing skipped between
OVERLAY_EVERY = 3  # after the hook, a text panel on every third slot: the footage stays the star


class TimelineError(Exception):
    """The visuals cannot fill the narration."""


@dataclass(frozen=True)
class Card:
    full: Path  # opaque, for slots with no footage
    overlay: Path | None  # see-through panel drawn over video; None: too big to cover footage with


@dataclass(frozen=True)
class TimelineItem:
    kind: Literal["shot", "image"]
    duration: float
    shot: Shot | None
    image: Path | None
    overlay: Path | None = None


def slot_length(duration: float, slot_s: float) -> float:
    return duration / ceil(duration / slot_s)


def _fitting(shots: list[Shot], slot: float) -> list[Shot]:
    return [s for s in shots if s.end - s.start >= slot - _EPSILON]


def _runs(shots: list[Shot]) -> list[Shot]:
    """Back-to-back scenes of one trailer joined into one stretch; a gap means a skipped scene in between."""
    runs: list[Shot] = []
    for shot in sorted(shots, key=lambda s: (str(s.source), s.start)):
        last = runs[-1] if runs else None
        if last and last.source == shot.source and shot.start - last.end <= ADJACENT_S:
            runs[-1] = replace(last, end=shot.end, score=max(last.score, shot.score))
        else:
            runs.append(shot)
    return runs


def _pieces(run: Shot, slot: float) -> list[Shot]:
    count = int((run.end - run.start + _EPSILON) // slot)
    return [replace(run, start=run.start + k * slot, end=run.start + (k + 1) * slot) for k in range(count)]


def _overlaps(a: Shot, b: Shot) -> bool:
    return a.source == b.source and a.start < b.end - _EPSILON and b.start < a.end - _EPSILON


def usable_trailer_shots(trailer: list[Shot], duration: float, *, slot_s: float, max_shot_s: float) -> list[Shot]:
    """The trailer shots the timeline can actually use: a whole slot long, and slots within the excerpt limit.

    Whole scenes first; fast-cut trailers (every scene shorter than a slot) add slot-long pieces of
    their back-to-back scenes, each still one excerpt within the limit.
    """
    slot = slot_length(duration, slot_s)
    if slot > max_shot_s:
        return []
    whole = _fitting(trailer, slot)
    pieces = sorted((p for run in _runs(trailer) for p in _pieces(run, slot)), key=lambda p: p.score, reverse=True)
    chosen = list(whole)
    for piece in pieces:
        if not any(_overlaps(piece, taken) for taken in chosen):
            chosen.append(piece)
    return chosen


def _overlay_for(index: int, cards: list[Card]) -> Path | None:
    """The hook on the first slot, then the single-fact panels in turn on every OVERLAY_EVERY-th slot."""
    if index == 0:
        return cards[0].overlay if cards else None
    facts = [c.overlay for c in cards[1:] if c.overlay is not None]
    if index % OVERLAY_EVERY != 1 or not facts:
        return None
    return facts[(index // OVERLAY_EVERY) % len(facts)]


def _full_card(shown: int, cards: list[Card]) -> Path:
    """Cards in order, then the facts again: the hook only opens the video."""
    if shown == 0 or len(cards) == 1:
        return cards[0].full
    return cards[1 + (shown - 1) % (len(cards) - 1)].full


def plan_timeline(
    duration: float,
    *,
    trailer: list[Shot],
    stock: list[Shot],
    stills: list[Path],
    cards: list[Card],
    slot_s: float,
    max_shot_s: float,
    max_trailer_share: float,
) -> list[TimelineItem]:
    """Equal slots, each with a background; video backgrounds sometimes get a text panel over them.

    Backgrounds: a fresh trailer shot on even slots while the trailer budget allows, else a screenshot
    of the story's own game, else stock footage (licensed, so it may repeat), else a card full screen.
    """
    count = ceil(duration / slot_s)
    slot = duration / count
    budget = max_trailer_share * duration
    unused = usable_trailer_shots(trailer, duration, slot_s=slot_s, max_shot_s=max_shot_s)
    stock = _fitting(stock, slot)
    used = 0.0
    shown = 0  # full-screen cards shown so far
    items: list[TimelineItem] = []
    for i in range(count):
        if i % 2 == 0 and unused and used + slot <= budget:
            chosen = unused.pop(0)
            used += slot
            background = TimelineItem("shot", slot, replace(chosen, end=chosen.start + slot), None)
        elif stills:
            background = TimelineItem("image", slot, None, stills[i % len(stills)])
        elif stock:
            chosen = stock[i % len(stock)]
            background = TimelineItem("shot", slot, replace(chosen, end=chosen.start + slot), None)
        elif cards:
            items.append(TimelineItem("image", slot, None, _full_card(shown, cards)))
            shown += 1
            continue
        else:
            raise TimelineError("no visuals available to fill the video (no images and no usable shots)")
        if background.kind == "shot":  # a panel over a screenshot would hide the screenshot
            background = replace(background, overlay=_overlay_for(i, cards))
        items.append(background)
    return items
