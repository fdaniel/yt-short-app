from pathlib import Path

from shorts.media.shots import Shot
from shorts.media.timeline import TimelineItem
from shorts.pipeline import _cover_source


def test_cover_uses_the_first_footage():
    shot = Shot(Path("t.mp4"), 1, 0.0, 4.0, 1.0)
    items = [TimelineItem("image", 3.0, None, Path("still_1.png")), TimelineItem("shot", 3.0, shot, None)]
    assert _cover_source(items) == shot


def test_cover_never_uses_a_text_card():
    items = [TimelineItem("image", 3.0, None, Path("card_hook.png")), TimelineItem("image", 3.0, None, Path("still_2.png"))]
    assert _cover_source(items) == Path("still_2.png")


def test_no_footage_no_cover():
    assert _cover_source([TimelineItem("image", 3.0, None, Path("card_facts.png"))]) is None
