import pytest

from shorts.clips.moments import best_window, find_moment

from tests.clips.helpers import gameplay


def test_the_loudest_busiest_stretch_is_chosen():
    loud = [-40.0] * 20 + [-10.0] * 10 + [-40.0] * 30
    motion = [1.0] * 20 + [20.0] * 10 + [1.0] * 30
    moment = best_window(loud, motion, 10, favour_end=False)
    assert (moment.start, moment.end) == (20, 30)


def test_a_pick_leans_towards_its_end_where_the_owner_pressed_the_key():
    flat = [-20.0] * 60
    moment = best_window(flat, [5.0] * 60, 30, favour_end=True)
    assert (moment.start, moment.end) == (30, 60)


def test_a_short_clip_is_used_whole():
    moment = best_window([-20.0] * 12, [5.0] * 12, 35, favour_end=True)
    assert (moment.start, moment.end) == (0, 12)


def test_the_score_compares_clips_with_each_other():
    quiet = best_window([-40.0] * 40, [1.0] * 40, 30, favour_end=False)
    action = best_window([-12.0] * 40, [15.0] * 40, 30, favour_end=False)
    assert action.score > quiet.score


def test_no_seconds_is_an_error():
    with pytest.raises(ValueError):
        best_window([], [], 30, favour_end=False)


def test_action_in_the_middle_of_a_pick_still_wins():
    loud = [-40.0] * 5 + [-8.0] * 20 + [-40.0] * 35
    motion = [1.0] * 5 + [25.0] * 20 + [1.0] * 35
    moment = best_window(loud, motion, 35, favour_end=True)
    assert moment.start <= 5 and moment.end >= 25


def test_a_long_recording_is_not_a_clip(tmp_path):
    from shorts.clips.moments import ClipTooLong

    with pytest.raises(ClipTooLong):
        find_moment(gameplay(tmp_path, seconds=8), 5, favour_end=True, timeout_s=120, max_s=5)


def test_a_real_clip_is_measured(tmp_path):
    moment = find_moment(gameplay(tmp_path, seconds=8), 5, favour_end=True, timeout_s=120)
    assert moment.end - moment.start == pytest.approx(5, abs=1)
    assert 0 <= moment.start and moment.end <= 8.5
