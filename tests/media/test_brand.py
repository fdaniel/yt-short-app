import re

import pytest

from shorts.media import brand


def _numbers(drawing: str) -> list[int]:
    return [int(n) for n in re.findall(r"-?\d+", drawing)]


def test_colours_are_written_blue_first_for_ass():
    assert brand.ass_colour((0xF4, 0x51, 0x1E)) == "&H001E51F4&"
    assert brand.ORANGE == "&H001E51F4&"


def test_the_brand_plays_over_the_action_from_the_first_frame():
    events = brand.intro(25.0)
    assert min(e.start for e in events) == 0.0  # nothing is put in front of the footage
    sweeps = [e for e in events if "\\move" in e.text]
    assert sweeps and all(e.end <= 0.5 for e in sweeps)


def test_the_badge_stays_until_the_last_word():
    badge = [e for e in brand.intro(25.0) if e.text.endswith("LD")]
    assert len(badge) == 1 and badge[0].end == 25.0


def test_the_badge_letters_sit_on_the_middle_of_the_circle():
    # \an5 centres the line box; capitals sit lower, so the letters are placed a little higher
    x, y, _ = brand.BADGE
    [letters] = [e for e in brand.intro(25.0) if e.text.endswith("LD")]
    assert f"\\pos({x},{y - 3})" in letters.text


def test_circles_are_drawn_inside_their_own_box_so_they_centre_on_their_position():
    for event in brand.intro(25.0) + brand.outro(25.0):
        if "\\an5" in event.text and "\\p1" in event.text:
            drawing = event.text.split("\\p1}")[1].split("{")[0]
            assert min(_numbers(drawing)) == 0


def test_the_outro_follows_the_last_word_and_lasts_the_outro_time():
    events = brand.outro(25.0)
    assert {(e.start, e.end) for e in events} == {(25.0, 25.0 + brand.OUTRO_S)}
    texts = " ".join(e.text for e in events)
    assert "LOADOUT DAILY" in texts and "TECH & GAMING NEWS, DAILY" in texts
    assert min(e.layer for e in events) > max(e.layer for e in brand.intro(25.0))  # drawn over everything


def test_between_intro_and_outro_only_the_badge_stays_on_screen():
    # clips change every few seconds; anything more mid-video was too busy
    lingering = [e for e in brand.intro(25.0) if e.end > 2.5]
    assert len(lingering) == 2 and all("\\move" not in e.text and "\\t(" in e.text for e in lingering)
    assert all(e.start >= 25.0 for e in brand.outro(25.0))
