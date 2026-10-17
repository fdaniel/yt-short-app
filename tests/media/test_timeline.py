from pathlib import Path

import pytest

from shorts.media.shots import Shot
from shorts.media.timeline import TimelineError, plan_timeline


def shot(i, length=6.0):
    return Shot(Path(f"t{i}.mp4"), i, 10.0, 10.0 + length, 1.0)


KW = dict(slot_s=3.5, max_shot_s=4.0, max_trailer_share=0.49)


def test_total_duration_exact():
    items = plan_timeline(41.3, [shot(i) for i in range(10)], [Path("c.png")], **KW)
    assert sum(i.duration for i in items) == pytest.approx(41.3, abs=0.01)


def test_trailer_limits():
    items = plan_timeline(50.0, [shot(i) for i in range(20)], [Path("c.png")], **KW)
    shots = [i for i in items if i.kind == "shot"]
    assert shots
    assert all(i.duration <= 4.0 for i in shots)
    assert sum(i.duration for i in shots) < 0.5 * 50.0
    assert len({(i.shot.source, i.shot.start) for i in shots}) == len(shots)


def test_shot_trimmed_to_slot():
    items = plan_timeline(30.0, [shot(1)], [Path("c.png")], **KW)
    first = items[0]
    assert first.kind == "shot"
    assert first.shot.end - first.shot.start == pytest.approx(first.duration)


def test_images_only_when_no_shots():
    items = plan_timeline(30.0, [], [Path("a.png"), Path("b.png")], **KW)
    assert {i.kind for i in items} == {"image"}
    assert [i.image.name for i in items[:3]] == ["a.png", "b.png", "a.png"]


def test_short_shots_skipped():
    items = plan_timeline(30.0, [shot(1, length=1.0)], [Path("a.png")], **KW)
    assert all(i.kind == "image" for i in items)


def test_shots_only_fill_gaps_with_nothing_raises():
    with pytest.raises(TimelineError, match="no visuals"):
        plan_timeline(30.0, [shot(i) for i in range(20)], [], **KW)


def test_nothing_to_show_raises():
    with pytest.raises(TimelineError, match="no visuals"):
        plan_timeline(30.0, [], [], **KW)
