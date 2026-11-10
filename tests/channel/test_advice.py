from datetime import UTC, timedelta

from shorts.channel.advice import build_report, grade_videos

from tests.channel.helpers import NOW, days, snapshot, video


def grades(snap):
    return {v.video.youtube_id: v for v in grade_videos(snap, tz=UTC)}


def test_a_video_far_above_its_kind_is_a_top_video_and_far_below_is_weak():
    snap = snapshot(video(1, views=1400), video(2, views=1500), video(3, views=1300), video(4, views=2500),
                    video(5, views=380))
    g = grades(snap)
    assert g["vid00000004xx"].grade == "top"
    assert g["vid00000005xx"].grade == "weak"
    assert g["vid00000001xx"].grade == "ok"


def test_videos_are_compared_with_their_own_kind():
    # app news at ~500 is normal for news; the same views would be weak for the owner's gameplay
    snap = snapshot(video(1, views=1400), video(2, views=1500), video(3, views=1300),
                    video(4, views=500, from_app=True), video(5, views=450, from_app=True), video(6, views=520, from_app=True))
    assert grades(snap)["vid00000004xx"].grade == "ok"


def test_a_video_younger_than_two_days_is_too_early_to_judge():
    snap = snapshot(video(1, views=1400), video(2, views=1500), video(3, views=1300), video(4, views=300, days_old=1))
    assert grades(snap)["vid00000004xx"].grade == "early"


def test_long_videos_are_not_graded_against_shorts():
    snap = snapshot(video(1, views=1400), video(2, views=1500), video(3, views=1300),
                    video(4, views=90, duration_s=600))
    assert "vid00000004xx" not in grades(snap)


def test_a_weak_video_says_when_viewers_swiped_away():
    snap = snapshot(video(1, views=1400), video(2, views=1500), video(3, views=1300),
                    video(4, views=380, engaged_views=150, analytics_views=380))
    reasons = " ".join(grades(snap)["vid00000004xx"].reasons)
    assert "39%" in reasons and "first second" in reasons


def test_a_late_upload_is_named():
    snap = snapshot(video(1, views=1400), video(2, views=1500), video(3, views=1300), video(4, views=380, hour=21))
    reasons = " ".join(grades(snap)["vid00000004xx"].reasons)
    assert "21:30" in reasons and "18" in reasons


def test_a_few_minutes_before_the_slot_is_not_late():
    from dataclasses import replace

    early = replace(video(4, views=380, hour=18), published_at=video(4, hour=17).published_at.replace(minute=45))
    snap = snapshot(video(1, views=1400), video(2, views=1500), video(3, views=1300), early)
    assert not any("Posted at" in r for r in grades(snap)["vid00000004xx"].reasons)


def test_viewers_leaving_early_is_named():
    snap = snapshot(video(1, views=1400), video(2, views=1500), video(3, views=1300),
                    video(4, views=380, avg_view_pct=38.0, duration_s=80))
    reasons = " ".join(grades(snap)["vid00000004xx"].reasons)
    assert "38%" in reasons and "1:20" in reasons


def tips(snap):
    return " | ".join(t.text for t in build_report(snap, tz=UTC).tips)


def test_missing_analytics_asks_to_reconnect():
    snap = snapshot(video(1), analytics_note="no access to YouTube Analytics yet")
    assert "youtube-connect" in tips(snap)


def test_too_few_own_uploads_this_week_is_flagged():
    snap = snapshot(video(1, days_old=1), video(2, days_old=3), video(3, days_old=9))
    assert "2 of your own Shorts in the last 7 days" in tips(snap)


def test_few_subscribers_per_view_is_flagged():
    snap = snapshot(video(1), days=days(views_per_day=1000, subs_per_day=0))
    assert "subscribe" in tips(snap).lower()


def test_no_long_video_this_week_is_flagged():
    assert "long video" in tips(snapshot(video(1))).lower()


def test_a_top_video_asks_for_a_part_two():
    snap = snapshot(video(1, views=1400), video(2, views=1500), video(3, views=1300),
                    video(4, views=4000, days_old=3, title="How to Get the FULL Forsaken Oath Armor"))
    assert "part 2" in tips(snap).lower() and "Forsaken Oath" in tips(snap)


def test_part_two_is_only_asked_for_your_own_recent_hits():
    snap = snapshot(video(1, views=500, from_app=True), video(2, views=450, from_app=True),
                    video(3, views=520, from_app=True), video(4, views=1500, from_app=True, title="Apex news"),
                    video(5, views=1400), video(6, views=1500), video(7, views=1300),
                    video(8, views=4000, days_old=6, title="Old armor guide"))
    text = tips(snap)
    assert "Apex news" not in text and "Old armor guide" not in text


def test_the_analytics_tip_does_not_repeat_itself():
    snap = snapshot(video(1), analytics_note="run python -m shorts youtube-connect once and press Allow")
    assert tips(snap).count("youtube-connect") == 1


def test_the_report_tracks_the_next_checkpoint():
    report = build_report(snapshot(video(1, views=6000), video(2), subscribers=40,
                                   long_hours_365d=12.5))
    progress = {t.label: (t.current, t.goal) for t in report.targets}
    assert progress["Subscribers"] == (40, 100)
    assert progress["Shorts over 5k views"] == (1, 1)
    assert progress["Long-video watch hours"] == (12.5, 50)


def test_partner_program_uses_the_rules_of_the_day():
    report = build_report(snapshot(video(1), subscribers=13, shorts_views_90d=33000, long_hours_365d=1.0))
    ypp = {t.label: t.goal for t in report.partner}
    assert ypp["Shorts views (90 days)"] == 10_000_000
    later = build_report(snapshot(video(1), taken_at=NOW + timedelta(days=90)))
    assert {t.label: t.goal for t in later.partner}["Shorts views (90 days)"] == 20_000_000


def test_the_report_shows_this_weeks_plan():
    assert build_report(snapshot(video(1))).week.number == 1


def test_an_old_snapshot_still_shows_todays_plan_week():
    later = NOW + timedelta(days=8)
    assert build_report(snapshot(video(1)), now=later).week.number == 2
