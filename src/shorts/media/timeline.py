"""Lay out visuals over the narration while enforcing the trailer limits (pure, no I/O)."""

from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path
from typing import Literal

from shorts.media.shots import Shot


class TimelineError(Exception):
    """The visuals cannot fill the narration."""


@dataclass(frozen=True)
class Card:
    full: Path  # opaque, for slots with no footage
    overlay: Path  # see-through panel, drawn over footage


@dataclass(frozen=True)
class TimelineItem:
    kind: Literal["shot", "image"]
    duration: float
    shot: Shot | None
    image: Path | None
    overlay: Path | None = None


def _fitting(shots: list[Shot], slot: float) -> list[Shot]:
    return [s for s in shots if s.end - s.start >= slot]


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
    """Equal slots, each with a background and, on the first and every odd slot, a text card over it.

    Backgrounds: a fresh trailer shot on even slots while the trailer budget allows, else stock
    footage (licensed, so it may repeat), else a screenshot, else the card itself full screen.
    """
    count = ceil(duration / slot_s)
    slot = duration / count
    budget = max_trailer_share * duration
    unused = _fitting(trailer, slot) if slot <= max_shot_s else []
    stock = _fitting(stock, slot)
    used = 0.0
    shown = 0  # cards shown so far, over footage or full screen
    items: list[TimelineItem] = []
    for i in range(count):
        wants_card = i == 0 or i % 2 == 1
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
            items.append(TimelineItem("image", slot, None, cards[shown % len(cards)].full))
            shown += 1
            continue
        else:
            raise TimelineError("no visuals available to fill the video (no images and no usable shots)")
        if wants_card and cards:
            background = replace(background, overlay=cards[shown % len(cards)].overlay)
            shown += 1
        items.append(background)
    return items
