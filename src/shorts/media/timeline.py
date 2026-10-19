"""Lay out visuals over the narration while enforcing the trailer limits (pure, no I/O)."""

from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path
from typing import Literal

from shorts.media.shots import Shot


_EPSILON = 1e-6  # clips cut to exactly one slot can come out a hair short in floating point
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


def usable_trailer_shots(trailer: list[Shot], duration: float, *, slot_s: float, max_shot_s: float) -> list[Shot]:
    """The trailer shots the timeline can actually use: a whole slot long, and slots within the excerpt limit."""
    slot = slot_length(duration, slot_s)
    return _fitting(trailer, slot) if slot <= max_shot_s else []


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

    Backgrounds: a fresh trailer shot on even slots while the trailer budget allows, else stock
    footage (licensed, so it may repeat), else a screenshot, else a card full screen.
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
        elif stock:
            chosen = stock[i % len(stock)]
            background = TimelineItem("shot", slot, replace(chosen, end=chosen.start + slot), None)
        elif stills:
            background = TimelineItem("image", slot, None, stills[i % len(stills)])
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
