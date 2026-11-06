"""Lay out visuals over the narration while enforcing the trailer limits (pure, no I/O)."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path
from typing import Literal

from shorts.media.shots import Shot


_EPSILON = 1e-6  # clips cut to exactly one slot can come out a hair short in floating point
ADJACENT_S = 0.15  # scenes this close are back to back: the trailer's own cut, nothing skipped between
SPREAD_SLOTS = 1  # trailer pieces picked first are at least this many slots apart
OVERLAY_EVERY = 3  # after the hook, a text panel on every third slot: the footage stays the star
MIN_PIECE_S = 1.0  # shorter than this, a clip is a flash, not a shot


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
    centre_crop: bool = False  # the centre 9:16 of the picture: the part checked for cut-off text


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


def _near(a: Shot, b: Shot, gap: float) -> bool:
    """Overlapping, or closer than `gap` seconds apart in the same trailer."""
    return a.source == b.source and a.start < b.end + gap - _EPSILON and b.start < a.end + gap - _EPSILON


def usable_trailer_shots(trailer: list[Shot], duration: float, *, slot_s: float, max_shot_s: float) -> list[Shot]:
    """The trailer shots the timeline can actually use: a whole slot long, and slots within the excerpt limit.

    Whole scenes first; fast-cut trailers (every scene shorter than a slot) add slot-long pieces of
    their back-to-back scenes, each still one excerpt within the limit.
    """
    slot = slot_length(duration, slot_s)
    if slot > max_shot_s:
        return []
    whole = sorted(_fitting(trailer, slot), key=lambda s: s.score, reverse=True)  # the liveliest opens the video
    pieces = sorted((p for run in _runs(trailer) for p in _pieces(run, slot)), key=lambda p: p.score, reverse=True)
    chosen = list(whole)
    # first pieces from different moments of the trailer, then the rest: side-by-side picks looked like a loop
    for gap in (SPREAD_SLOTS * slot, 0.0):
        for piece in pieces:
            if piece not in chosen and not any(_near(piece, taken, gap) for taken in chosen):
                chosen.append(piece)
    return chosen


def _overlay_for(index: int, cards: list[Card]) -> Path | None:
    """Nothing over the first slot, then the single-fact panels in turn on every OVERLAY_EVERY-th slot.

    The first second decides the swipe: a text box over it read as a news slide (7 in 10 swiped away);
    the hook is spoken and captioned anyway.
    """
    if index == 0:
        return None
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
    clips: Sequence[Shot] = (),
) -> list[TimelineItem]:
    """Equal slots, each with a background; video backgrounds sometimes get a text panel over them.

    Backgrounds: a fresh trailer shot on even slots while the moving-footage budget allows, or else, between
    photos, a fresh piece of the company's own clips; else a screenshot or photo, else stock footage
    (licensed, so it may repeat), else a card full screen. `clips` are the official clips, also in `stock`.
    """
    count = ceil(duration / slot_s)
    slot = duration / count
    budget = max_trailer_share * duration
    unused = usable_trailer_shots(trailer, duration, slot_s=slot_s, max_shot_s=max_shot_s)
    stock = _fitting(stock, slot)
    fresh_clips = _fitting(list(clips), slot)
    used = 0.0  # seconds of trailer and official clips: together under the share
    shown = 0  # full-screen cards shown so far
    stills_shown = stock_shown = 0  # each in turn: all of them before any repeats
    items: list[TimelineItem] = []
    for i in range(count):
        moving_turn = i % 2 == 0 and used + slot <= budget
        # with photos to show, the clips take turns with them: photos alone made the iPad mini a slideshow
        source = unused if unused else fresh_clips if stills else []
        if moving_turn and source:
            chosen = source.pop(0)
            used += slot
            background = TimelineItem("shot", slot, replace(chosen, end=chosen.start + slot), None)
        elif stills:
            background = TimelineItem("image", slot, None, stills[stills_shown % len(stills)])
            stills_shown += 1
        elif stock:
            chosen = stock[stock_shown % len(stock)]
            stock_shown += 1
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


def _spread_pick(clips: list[Shot], seconds: float) -> list[Shot]:
    """Clips evenly spaced over the trailer until they add up to `seconds`, then the gaps in between."""
    ordered = sorted(clips, key=lambda c: (str(c.source), c.start))
    mean = sum(c.end - c.start for c in ordered) / len(ordered)
    count = min(len(ordered), ceil(seconds / mean - _EPSILON))
    step = (len(ordered) - 1) / max(count - 1, 1)
    picked = list(dict.fromkeys(ordered[round(k * step)] for k in range(count)))
    for c in ordered:
        if sum(p.end - p.start for p in picked) >= seconds - _EPSILON:
            break
        if c not in picked:
            picked.append(c)
    return sorted(picked, key=lambda c: (str(c.source), c.start))


def _no_flash_at_the_end(lengths: list[float]) -> list[float]:
    """A last piece shorter than MIN_PIECE_S takes the missing time from the pieces before it, the longest
    first and the opener last, never leaving one of them shorter than MIN_PIECE_S."""
    if len(lengths) < 2 or lengths[-1] >= MIN_PIECE_S:
        return lengths
    out, deficit = list(lengths), MIN_PIECE_S - lengths[-1]
    donors = sorted(range(1, len(out) - 1), key=lambda i: out[i], reverse=True) + [0]
    for i in donors:
        give = min(deficit, max(0.0, out[i] - MIN_PIECE_S))
        out[i] -= give
        deficit -= give
        if deficit <= _EPSILON:
            break
    out[-1] = MIN_PIECE_S - deficit
    return out


def plan_moving_timeline(duration: float, clips: Sequence[Shot]) -> list[TimelineItem]:
    """Only moving trailer footage, each clip already checked for cut-off text: the liveliest whole clip
    opens, then clips from across the trailers in their own order. No screenshots, no text panels."""
    total = sum(c.end - c.start for c in clips)
    if total < duration - _EPSILON:
        raise TimelineError(f"only {total:.1f}s of clean trailer footage for a {duration:.1f}s video")
    longest = max(c.end - c.start for c in clips)
    opener = max((c for c in clips if c.end - c.start >= longest - _EPSILON), key=lambda c: c.score)
    rest = [c for c in clips if c is not opener]
    needed = duration - (opener.end - opener.start)
    chosen = [opener] + (_spread_pick(rest, needed) if needed > _EPSILON else [])
    lengths, left = [], duration
    for c in chosen:
        if left <= _EPSILON:
            break
        lengths.append(min(c.end - c.start, left))
        left -= lengths[-1]
    return [TimelineItem("shot", length, replace(c, end=c.start + length), None, centre_crop=True)
            for c, length in zip(chosen, _no_flash_at_the_end(lengths))]
