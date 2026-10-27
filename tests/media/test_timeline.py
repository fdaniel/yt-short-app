from pathlib import Path

import pytest

from shorts.media.shots import Shot
from shorts.media.timeline import Card, TimelineError, plan_timeline


def shot(i, length=6.0, name="t"):
    return Shot(Path(f"{name}{i}.mp4"), i, 10.0, 10.0 + length, 1.0)


def card(name, overlay=True):
    return Card(Path(f"{name}.png"), Path(f"{name}_overlay.png") if overlay else None)


CARDS = [card("hook"), card("facts", overlay=False), card("fact0"), card("fact1")]
KW = dict(slot_s=3.5, max_shot_s=4.0, max_trailer_share=0.49)


def plan(duration, trailer=(), stock=(), stills=(), cards=CARDS, clips=()):
    return plan_timeline(duration, trailer=list(trailer), stock=list(stock), stills=list(stills), cards=list(cards),
                         clips=list(clips), **KW)


def test_total_duration_exact():
    items = plan(41.3, trailer=[shot(i) for i in range(10)])
    assert sum(i.duration for i in items) == pytest.approx(41.3, abs=0.01)


def test_trailer_limits():
    items = plan(50.0, trailer=[shot(i) for i in range(20)])
    shots = [i for i in items if i.kind == "shot"]
    assert shots
    assert all(i.duration <= 4.0 for i in shots)
    assert sum(i.duration for i in shots) < 0.5 * 50.0
    assert len({(i.shot.source, i.shot.start) for i in shots}) == len(shots)


def test_shot_trimmed_to_slot():
    first = plan(30.0, trailer=[shot(1)])[0]
    assert first.kind == "shot"
    assert first.shot.end - first.shot.start == pytest.approx(first.duration)


def test_stock_footage_fills_what_the_trailer_budget_leaves():
    items = plan(40.0, trailer=[shot(i) for i in range(20)], stock=[shot(i, name="s") for i in range(20)])
    assert all(i.kind == "shot" for i in items)  # no full-screen text cards
    trailer = sum(i.duration for i in items if i.shot.source.name.startswith("t"))
    assert trailer < 0.5 * 40.0


def test_stock_alone_fills_the_video_and_repeats_when_short():
    items = plan(40.0, stock=[shot(1, name="s"), shot(2, name="s")])
    assert all(i.kind == "shot" and i.shot.source.name.startswith("s") for i in items)
    assert all(i.shot.end - i.shot.start == pytest.approx(i.duration) for i in items)


def test_opening_slot_is_clean_footage_then_a_fact_every_third_slot():
    # 7 in 10 viewers swiped past a first frame covered by a text box: the first slot shows footage only
    items = plan(40.0, stock=[shot(i, name="s") for i in range(20)])
    overlays = [i.overlay.name if i.overlay else None for i in items]
    assert overlays[:8] == [None, "fact0_overlay.png", None, None, "fact1_overlay.png", None, None,
                            "fact0_overlay.png"]  # the fact table is never an overlay


def test_opening_slot_gets_the_trailer_shot_with_the_most_motion():
    calm, lively = Shot(Path("t.mp4"), 1, 10.0, 16.0, 0.2), Shot(Path("t.mp4"), 1, 20.0, 26.0, 9.0)
    items = plan(30.0, trailer=[calm, lively], stills=[Path("a.jpg")])
    assert items[0].shot.start == 20.0


def test_stills_are_backgrounds_with_nothing_over_them():
    # a panel over a screenshot hides the screenshot
    items = plan(30.0, stills=[Path("a.jpg"), Path("b.jpg")])
    assert [i.image for i in items[:3]] == [Path("a.jpg"), Path("b.jpg"), Path("a.jpg")]
    assert all(i.kind == "image" and i.overlay is None for i in items)


def test_full_cards_only_without_any_footage():
    items = plan(30.0)
    assert {i.kind for i in items} == {"image"} and all(i.overlay is None for i in items)
    assert [i.image.name for i in items[:5]] == ["hook.png", "facts.png", "fact0.png", "fact1.png", "facts.png"]


def test_pieces_cut_to_exactly_one_slot_are_used():
    # 42 s / 12 slots = 3.5 s, and 4.6 - 1.1 is 3.4999999999999996 in floating point
    items = plan(42.0, stock=[Shot(Path("s.mp4"), 1, 1.1, 4.6, 1.0)], cards=[])
    assert all(i.kind == "shot" for i in items)


def test_short_shots_skipped():
    items = plan(30.0, trailer=[shot(1, length=1.0)])
    assert all(i.kind == "image" for i in items)


def test_trailer_without_anything_for_the_other_slots_raises():
    with pytest.raises(TimelineError, match="no visuals"):
        plan(30.0, trailer=[shot(i) for i in range(20)], cards=[])


def test_nothing_to_show_raises():
    with pytest.raises(TimelineError, match="no visuals"):
        plan(30.0, cards=[])


def test_game_screenshots_come_before_generic_stock():
    # a cat game must show the game, not a stock motherboard
    items = plan(30.0, stock=[shot(i, name="s") for i in range(10)], stills=[Path("a.jpg"), Path("b.jpg")])
    assert {i.kind for i in items} == {"image"}


def fast_cuts(start=10.0, count=12, length=1.5, gap=0.0):
    """A fast-cut trailer: back-to-back scenes, each shorter than a slot."""
    return [Shot(Path("t.mp4"), 1, start + i * (length + gap), start + i * (length + gap) + length, 1.0)
            for i in range(count)]


def test_fast_cut_trailer_is_used_in_continuous_pieces():
    items = plan(30.0, trailer=fast_cuts(), stills=[Path("a.jpg")])
    trailer = [i for i in items if i.kind == "shot"]
    assert trailer, "a fast-cut trailer must still give moving footage"
    assert all(i.shot.end - i.shot.start <= KW["max_shot_s"] + 1e-6 for i in trailer)
    assert sum(i.duration for i in trailer) <= KW["max_trailer_share"] * 30.0 + 1e-6


def test_pieces_never_overlap():
    items = plan(30.0, trailer=fast_cuts(count=30), stills=[Path("a.jpg")])
    spans = sorted((i.shot.start, i.shot.end) for i in items if i.kind == "shot")
    assert all(a_end <= b_start + 1e-6 for (_, a_end), (b_start, _) in zip(spans, spans[1:]))


def test_scenes_with_a_gap_between_are_not_joined():
    # a skipped dark or too-short scene sits in the gap: never bridge over it
    items = plan(30.0, trailer=fast_cuts(gap=0.5), stills=[Path("a.jpg")])
    assert {i.kind for i in items} == {"image"}


def test_every_screenshot_is_shown_before_any_repeats():
    stills = [Path(f"{n}.jpg") for n in "abcdef"]
    items = plan(40.0, stills=stills)
    shown = [i.image.name for i in items if i.kind == "image"]
    assert shown[:6] == [f"{n}.jpg" for n in "abcdef"]


def test_screenshots_between_trailer_shots_do_not_repeat_while_unused_ones_remain():
    # Crimson Desert: 4 screenshots on every other slot showed #2, #4, #2, #4 and never #1 or #3
    stills = [Path(f"{n}.jpg") for n in "abcd"]
    items = plan(40.0, trailer=[shot(i) for i in range(10)], stills=stills)
    shown = [i.image.name for i in items if i.kind == "image"]
    assert sorted(shown[:4]) == ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]


def test_stock_clips_between_trailer_shots_are_all_used_before_any_repeats():
    items = plan(40.0, trailer=[shot(i) for i in range(10)], stock=[shot(i, name="s") for i in range(4)])
    used = [i.shot.source.name for i in items if i.shot.source.name.startswith("s")]
    assert len(set(used[:4])) == 4


def test_trailer_pieces_come_from_different_moments_of_the_trailer():
    # one long stretch of back-to-back scenes: the picks must spread out, not sit side by side
    run = [Shot(Path("t.mp4"), 1, 10.0 + i * 1.5, 11.5 + i * 1.5, float(i)) for i in range(40)]
    items = plan(30.0, trailer=run, stills=[Path(f"{n}.jpg") for n in "abcdefgh"])
    starts = sorted(i.shot.start for i in items if i.kind == "shot")
    slot = items[0].duration
    assert all(b - a >= 2 * slot - 1e-6 for a, b in zip(starts, starts[1:]))


def test_official_clips_take_turns_with_the_photos_within_the_footage_limit():
    # the iPad mini story: 12 press photos left Apple's own clips unused, a slideshow
    stills = [Path(f"{n}.jpg") for n in "abcdefghijkl"]
    items = plan(30.0, stills=stills, clips=[shot(i, name="c") for i in range(6)])
    clips = [i for i in items if i.kind == "shot"]
    assert items[0].kind == "shot" and items[1].kind == "image"  # moving footage opens the video
    assert sum(i.duration for i in clips) < 0.5 * 30.0
    assert len({(i.shot.source, i.shot.start) for i in clips}) == len(clips)  # none shown twice


def test_clips_share_the_footage_limit_with_the_trailer():
    items = plan(40.0, trailer=[shot(i) for i in range(20)], stills=[Path("a.jpg")],
                 clips=[shot(i, name="c") for i in range(20)])
    moving = sum(i.duration for i in items if i.kind == "shot")
    assert moving < 0.5 * 40.0
