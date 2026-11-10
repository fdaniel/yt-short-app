from datetime import date

from shorts.channel.models import DayStats, Snapshot

from tests.channel.helpers import NOW, snapshot, video


def test_a_snapshot_survives_a_round_trip_through_json():
    original = snapshot(video(1, engaged_views=600, analytics_views=900, avg_view_pct=81.5, subs_gained=2), video(2, from_app=True),
                        days=(DayStats(date(2026, 11, 9), 740, 1, 120.5),), shorts_views_90d=33000,
                        long_hours_365d=0.4, analytics_note="")
    assert Snapshot.from_json(original.to_json()) == original


def test_videos_up_to_three_minutes_are_shorts():
    assert video(duration_s=180).is_short
    assert not video(duration_s=181).is_short


def test_stayed_share_compares_numbers_from_the_same_day():
    # Analytics lag days behind the live view count: dividing by the live count makes new Shorts look bad
    assert video(views=3000, engaged_views=640, analytics_views=1000).stayed == 0.64
    assert video(views=1000, engaged_views=640).stayed is None
    assert video(views=0, engaged_views=0, analytics_views=0).stayed is None


def test_age_is_measured_from_the_snapshot_time():
    assert video(days_old=3).age_days(NOW) > 2.5
