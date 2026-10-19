from pathlib import Path

import pytest

from shorts.media.shots import Shot
from shorts.media.timeline import Card, TimelineError, plan_timeline


def shot(i, length=6.0, name="t"):
    return Shot(Path(f"{name}{i}.mp4"), i, 10.0, 10.0 + length, 1.0)


def card(name):
    return Card(Path(f"{name}.png"), Path(f"{name}_overlay.png"))


CARDS = [card("hook"), card("facts"), card("fact0")]
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


def test_text_goes_over_footage_hook_first():
    items = plan(30.0, stock=[shot(i, name="s") for i in range(20)])
    assert items[0].overlay == Path("hook_overlay.png")
    assert [i.overlay for i in items[1:4]] == [Path("facts_overlay.png"), None, Path("fact0_overlay.png")]


def test_stills_are_backgrounds_when_there_is_no_video():
    items = plan(30.0, stills=[Path("a.jpg"), Path("b.jpg")])
    assert [i.image for i in items[:3]] == [Path("a.jpg"), Path("b.jpg"), Path("a.jpg")]
    assert items[0].overlay == Path("hook_overlay.png") and items[0].kind == "image"


def test_full_cards_only_without_any_footage():
    items = plan(30.0)
    assert {i.kind for i in items} == {"image"} and all(i.overlay is None for i in items)
    assert [i.image.name for i in items[:3]] == ["hook.png", "facts.png", "fact0.png"]


def test_short_shots_skipped():
    items = plan(30.0, trailer=[shot(1, length=1.0)])
    assert all(i.kind == "image" for i in items)


def test_trailer_without_anything_for_the_other_slots_raises():
    with pytest.raises(TimelineError, match="no visuals"):
        plan(30.0, trailer=[shot(i) for i in range(20)], cards=[])


def test_nothing_to_show_raises():
    with pytest.raises(TimelineError, match="no visuals"):
        plan(30.0, cards=[])
