"""Lay out visuals over the narration while enforcing the trailer limits (pure, no I/O)."""

from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path
from typing import Literal

from shorts.media.shots import Shot


class TimelineError(Exception):
    """The visuals cannot fill the narration."""


@dataclass(frozen=True)
class TimelineItem:
    kind: Literal["shot", "image"]
    duration: float
    shot: Shot | None
    image: Path | None


def plan_timeline(
    duration: float,
    shots: list[Shot],
    images: list[Path],
    *,
    slot_s: float,
    max_shot_s: float,
    max_trailer_share: float,
) -> list[TimelineItem]:
    """Equal slots; even slots take a fresh trailer shot while the trailer budget allows."""
    count = ceil(duration / slot_s)
    slot = duration / count
    budget = max_trailer_share * duration
    unused = [s for s in shots if s.end - s.start >= slot]
    used = 0.0
    image_index = 0
    items: list[TimelineItem] = []
    for i in range(count):
        if i % 2 == 0 and unused and slot <= max_shot_s and used + slot <= budget:
            chosen = unused.pop(0)
            items.append(TimelineItem("shot", slot, replace(chosen, end=chosen.start + slot), None))
            used += slot
        elif images:
            items.append(TimelineItem("image", slot, None, images[image_index % len(images)]))
            image_index += 1
        else:
            raise TimelineError("no visuals available to fill the video (no images and no usable shots)")
    return items
