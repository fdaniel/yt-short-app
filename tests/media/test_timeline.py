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


def plan(duration, trailer=(), stock=(), stills=(), cards=CARDS):
    return plan_timeline(duration, trailer=list(trailer), stock=list(stock), stills=list(stills), cards=list(cards),
                         **KW)


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


def test_text_goes_over_footage_hook_first_then_every_third_slot():
    items = plan(40.0, stock=[shot(i, name="s") for i in range(20)])
    overlays = [i.overlay.name if i.overlay else None for i in items]
    assert overlays[:8] == ["hook_overlay.png", "fact0_overlay.png", None, None, "fact1_overlay.png", None, None,
                            "fact0_overlay.png"]  # the hook is not repeated; the fact table is never an overlay


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
