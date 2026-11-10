import json
from datetime import UTC, date, datetime

import httplib2
import pytest
from googleapiclient.errors import HttpError

from shorts.channel.fetch import ChannelFetchError, fetch_snapshot, parse_duration

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class _Call:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Resource:
    def __init__(self, owner, name):
        self._owner, self._name = owner, name

    def list(self, **kwargs):
        self._owner.calls.append((self._name, kwargs))
        return _Call(self._owner.answers[self._name](kwargs))

    query = list


class FakeYouTube:
    def __init__(self, videos):
        self.calls = []
        self.answers = {
            "channels": lambda kw: {"items": [{"statistics": {"subscriberCount": "13", "viewCount": "33907",
                                                              "videoCount": "40"},
                                               "contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}}}]},
            "playlistItems": lambda kw: {"items": [{"contentDetails": {"videoId": v["id"]}} for v in videos]},
            "videos": lambda kw: {"items": videos},
        }

    def channels(self):
        return _Resource(self, "channels")

    def playlistItems(self):  # noqa: N802 (Google's name)
        return _Resource(self, "playlistItems")

    def videos(self):
        return _Resource(self, "videos")


def yt_video(vid, title="How to Get the Armor", views="1000", privacy="public", duration="PT45S",
             published="2026-11-05T19:30:00Z"):
    return {"id": vid, "snippet": {"title": title, "publishedAt": published},
            "statistics": {"viewCount": views, "likeCount": "20", "commentCount": "2"},
            "contentDetails": {"duration": duration}, "status": {"privacyStatus": privacy}}


def http_error(status=400, message="Unknown identifier (engagedViews)"):
    return HttpError(httplib2.Response({"status": status}), json.dumps({"error": {"message": message}}).encode())


class FakeAnalytics:
    def __init__(self, refuse_engaged=False, broken=False, refuse_videos=None):
        self.calls, self.refuse_engaged, self.broken = [], refuse_engaged, broken
        self.refuse_videos = refuse_videos
        self.answers = {"reports": self._answer}

    def reports(self):
        return _Resource(self, "reports")

    def _answer(self, kw):
        if self.broken:
            return http_error(403, "Insufficient permission")
        dims = kw.get("dimensions")
        if dims == "video":
            if self.refuse_videos:
                return self.refuse_videos
            if self.refuse_engaged and "engagedViews" in kw["metrics"]:
                return http_error()
            names = ["video", *kw["metrics"].split(",")]
            values = {"views": 1000, "engagedViews": 640, "averageViewPercentage": 81.5, "averageViewDuration": 36,
                      "subscribersGained": 2, "shares": 3}
            return {"columnHeaders": [{"name": n} for n in names],
                    "rows": [["v1", *[values[n] for n in names[1:]]]]}
        if dims == "day":
            return {"columnHeaders": [{"name": "day"}, {"name": "views"}, {"name": "subscribersGained"},
                                      {"name": "estimatedMinutesWatched"}],
                    "rows": [["2026-11-08", 2100, 1, 300], ["2026-11-09", 740, 0, 110]]}
        if dims == "creatorContentType":
            metric = kw["metrics"]
            if metric == "engagedViews" and self.refuse_engaged:
                return http_error()
            rows = {"views": [["SHORTS", 33000], ["VIDEO_ON_DEMAND", 12]],
                    "engagedViews": [["SHORTS", 21000], ["VIDEO_ON_DEMAND", 10]],
                    "estimatedMinutesWatched": [["SHORTS", 9000], ["VIDEO_ON_DEMAND", 30]]}[metric]
            return {"columnHeaders": [{"name": "creatorContentType"}, {"name": metric}], "rows": rows}
        raise AssertionError(f"unexpected query {kw}")


def test_durations_are_read_from_youtubes_format():
    assert parse_duration("PT45S") == 45
    assert parse_duration("PT1M20S") == 80
    assert parse_duration("PT1H2M3S") == 3723
    assert parse_duration("P0D") == 0


def test_channel_totals_and_public_videos_are_read():
    youtube = FakeYouTube([yt_video("v1", duration="PT1M20S"), yt_video("v2", privacy="private")])
    snap = fetch_snapshot(youtube, None, app_ids={"v1"}, now=NOW)
    assert (snap.subscribers, snap.total_views, snap.video_count) == (13, 33907, 40)
    assert [v.youtube_id for v in snap.videos] == ["v1"]
    first = snap.videos[0]
    assert (first.duration_s, first.views, first.likes, first.from_app) == (80, 1000, 20, True)
    assert first.published_at == datetime(2026, 11, 5, 19, 30, tzinfo=UTC)


def test_without_analytics_the_snapshot_says_why():
    snap = fetch_snapshot(FakeYouTube([yt_video("v1")]), None, app_ids=set(), now=NOW,
                          analytics_note="no access yet")
    assert snap.analytics_note == "no access yet"
    assert snap.videos[0].engaged_views is None


def test_analytics_numbers_are_added_to_each_video():
    snap = fetch_snapshot(FakeYouTube([yt_video("v1")]), FakeAnalytics(), app_ids=set(), now=NOW)
    v = snap.videos[0]
    assert (v.engaged_views, v.avg_view_pct, v.avg_view_s, v.subs_gained, v.shares) == (640, 81.5, 36, 2, 3)
    assert v.analytics_views == 1000
    assert snap.analytics_note == ""


def test_if_youtube_does_not_know_engaged_views_the_rest_still_comes():
    snap = fetch_snapshot(FakeYouTube([yt_video("v1")]), FakeAnalytics(refuse_engaged=True), app_ids=set(), now=NOW)
    assert snap.videos[0].engaged_views is None
    assert snap.videos[0].avg_view_pct == 81.5


def test_daily_numbers_and_partner_program_totals_are_read():
    snap = fetch_snapshot(FakeYouTube([yt_video("v1")]), FakeAnalytics(), app_ids=set(), now=NOW)
    assert [(d.day, d.views, d.subs_gained) for d in snap.days] == [(date(2026, 11, 8), 2100, 1),
                                                                    (date(2026, 11, 9), 740, 0)]
    assert snap.shorts_views_90d == 21000  # the Partner Program counts engaged views
    assert snap.long_hours_365d == 0.5


def test_partner_program_falls_back_to_plain_views():
    snap = fetch_snapshot(FakeYouTube([yt_video("v1")]), FakeAnalytics(refuse_engaged=True), app_ids=set(), now=NOW)
    assert snap.shorts_views_90d == 33000


def test_a_refused_video_report_keeps_the_other_analytics():
    analytics = FakeAnalytics(refuse_videos=http_error(403, "quota exceeded"))
    snap = fetch_snapshot(FakeYouTube([yt_video("v1")]), analytics, app_ids=set(), now=NOW)
    assert snap.days and snap.shorts_views_90d == 21000
    assert snap.videos[0].avg_view_pct is None and "quota exceeded" in snap.analytics_note
    video_queries = [kw for name, kw in analytics.calls if kw.get("dimensions") == "video"]
    assert len(video_queries) == 1  # only an unknown engagedViews is worth a second try


def test_videos_with_an_unknown_length_are_left_out():
    youtube = FakeYouTube([yt_video("v1"), yt_video("v2", duration="P0D")])
    assert [v.youtube_id for v in fetch_snapshot(youtube, None, app_ids=set(), now=NOW).videos] == ["v1"]


def test_a_malformed_video_is_skipped():
    broken = yt_video("v2")
    del broken["snippet"]["publishedAt"]
    youtube = FakeYouTube([yt_video("v1"), broken])
    assert [v.youtube_id for v in fetch_snapshot(youtube, None, app_ids=set(), now=NOW).videos] == ["v1"]


def test_video_analytics_start_a_day_early_for_pacific_time():
    analytics = FakeAnalytics()
    fetch_snapshot(FakeYouTube([yt_video("v1", published="2026-11-05T03:00:00Z")]), analytics, app_ids=set(), now=NOW)
    video_query = next(kw for name, kw in analytics.calls if kw.get("dimensions") == "video")
    assert video_query["startDate"] == "2026-11-04"


def test_refused_analytics_keep_the_basic_numbers_and_explain():
    snap = fetch_snapshot(FakeYouTube([yt_video("v1")]), FakeAnalytics(broken=True), app_ids=set(), now=NOW)
    assert snap.videos[0].views == 1000
    assert "Insufficient permission" in snap.analytics_note


def test_a_refused_channel_request_is_an_error():
    youtube = FakeYouTube([])
    youtube.answers["channels"] = lambda kw: http_error(403, "quota exceeded")
    with pytest.raises(ChannelFetchError, match="quota exceeded"):
        fetch_snapshot(youtube, None, app_ids=set(), now=NOW)
