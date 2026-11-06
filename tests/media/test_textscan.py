from pathlib import Path

import numpy as np
import pytest

from shorts.media.textscan import (
    CELL_S,
    Moment,
    TextBox,
    clean_clips,
    frame_problem,
    scan_trailer,
    spread_problems,
)

W, H = 1920, 1080  # the centre 9:16 crop of a full-height picture is x 656..1264
SOURCE = Path("trailer.mp4")


def box(left, right, text="ARMOR", confidence=0.9):
    return TextBox(left, right, text, confidence)


def test_a_word_crossing_the_crop_edge_is_cut_off():
    assert frame_problem([box(600, 800)], brightness=100, width=W, height=H) == "ARMOR"


def test_a_word_inside_the_crop_is_fine():
    assert frame_problem([box(800, 1000)], brightness=100, width=W, height=H) is None


def test_a_word_outside_the_crop_is_never_seen():
    assert frame_problem([box(100, 400)], brightness=100, width=W, height=H) is None


def test_short_or_unsure_text_is_ignored():
    assert frame_problem([box(600, 800, text="AB")], brightness=100, width=W, height=H) is None
    assert frame_problem([box(600, 800, confidence=0.3)], brightness=100, width=W, height=H) is None


def test_small_print_inside_the_crop_is_rejected_too():
    legal = "Requires in-game purchases"
    assert frame_problem([box(800, 1000, text=legal)], brightness=100, width=W, height=H) == legal


def test_a_letterboxed_scene_has_a_narrower_crop():
    # bars leave a 800 px tall picture: its 9:16 crop is x 735..1185, so x 700 is cut off
    assert frame_problem([box(700, 900)], brightness=100, width=W, height=H, picture_height=800) == "ARMOR"
    assert frame_problem([box(700, 900)], brightness=100, width=W, height=H) is None


def test_dark_and_white_flash_moments_are_skipped():
    assert frame_problem([], brightness=20, width=W, height=H) == "dark"
    assert frame_problem([], brightness=240, width=W, height=H) == "white flash"
    assert frame_problem([], brightness=120, width=W, height=H) is None


def moments(*problems):
    return [Moment(i * CELL_S, p, motion=float(i)) for i, p in enumerate(problems)]


def test_the_moments_next_to_a_problem_count_as_problems():
    # text fades in and out between two samples
    spread = spread_problems(moments(None, None, "ARMOR", None, None))
    assert [m.problem is not None for m in spread] == [False, True, True, True, False]


def test_clean_clips_are_cut_from_runs_of_clean_moments():
    clips = clean_clips(moments(*([None] * 14), "dark", *([None] * 3)), SOURCE, asset_id=7)
    # 14 clean moments = 5.6 s: one 4 s clip and one 1.6 s clip; the 3 after "dark" (1.2 s) are too short
    assert [(round(c.start, 1), round(c.end, 1)) for c in clips] == [(0.0, 4.0), (4.0, 5.6)]
    assert all(c.source == SOURCE and c.asset_id == 7 for c in clips)


def test_a_clip_scores_its_motion():
    clips = clean_clips(moments(None, None, None, None, None), SOURCE, asset_id=1)
    assert clips[0].score == pytest.approx(2.0)  # mean motion of moments 0..4


class FakeReader:
    """Text found in frames whose mean brightness is the marked one."""

    def __init__(self):
        self.calls = 0

    def __call__(self, frame):
        self.calls += 1
        return [TextBox(0.3 * frame.shape[1], 0.45 * frame.shape[1], "BATTERY", 0.9)] if frame.mean() > 150 else []


def test_scan_finds_the_clean_parts_of_a_trailer(tmp_path):
    import cv2

    path = tmp_path / "t.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 180))
    for i in range(120):  # 12 s: grey, then 4 s with a caption across the crop edge, then grey
        shade = 200 if 40 <= i < 80 else 90 + (i % 5) * 5
        writer.write(np.full((180, 320, 3), shade, np.uint8))
    writer.release()
    reader = FakeReader()
    clips = scan_trailer(path, 3, reader, start=0.0, end=12.0)
    assert reader.calls > 0 and clips
    assert all(c.end <= 3.7 or c.start >= 8.3 for c in clips)  # nothing near the caption
    assert all(c.asset_id == 3 for c in clips)


def test_a_letterboxed_scene_is_checked_against_the_full_height_crop_too():
    # the render may still crop the full height: x 600-700 then crosses its edge at 656
    assert frame_problem([box(600, 700)], brightness=100, width=W, height=H, picture_height=800) == "ARMOR"
