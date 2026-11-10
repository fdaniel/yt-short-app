"""Read the channel's numbers from the YouTube Data API and, when allowed, YouTube Analytics.

Analytics are optional: without them the snapshot still has views, likes and comments, and says why the rest
is missing. YouTube Analytics lag about two days behind.
"""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httplib2
from googleapiclient.errors import HttpError

from shorts.channel.models import DayStats, Snapshot, VideoStats

log = logging.getLogger(__name__)

MAX_VIDEOS = 50  # one page of uploads: about seven weeks at the planned pace
VIDEO_METRICS = ("views", "engagedViews", "averageViewPercentage", "averageViewDuration", "subscribersGained",
                 "shares")
DAYS_BACK = 28
_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")
_NETWORK_ERRORS = (OSError, httplib2.HttpLib2Error)


class ChannelFetchError(Exception):
    """YouTube did not give the channel's basic numbers."""


def parse_duration(text: str) -> int:
    """Seconds in an ISO 8601 duration as YouTube writes it ("PT1M20S")."""
    match = _DURATION.fullmatch(text or "")
    if not match:
        return 0
    d, h, m, s = (int(g or 0) for g in match.groups())
    return ((d * 24 + h) * 60 + m) * 60 + s


def _message(exc: HttpError) -> str:
    try:
        return json.loads(exc.content)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return str(exc)


def _data(call: Callable[[], Any]) -> dict[str, Any]:
    try:
        return call().execute()
    except HttpError as exc:
        raise ChannelFetchError(f"YouTube refused: {_message(exc)}") from exc
    except _NETWORK_ERRORS as exc:
        raise ChannelFetchError(f"could not reach YouTube: {exc}") from exc


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _video_from(item: dict[str, Any], app_ids: set[str]) -> VideoStats | None:
    """One public video with a known length; None for anything else, or for data YouTube garbled."""
    try:
        if item.get("status", {}).get("privacyStatus") != "public":
            return None  # private and scheduled videos have no audience yet
        duration = parse_duration(item.get("contentDetails", {}).get("duration", ""))
        if not duration:
            return None  # premieres and live streams have no length yet
        stats, snippet = item.get("statistics", {}), item["snippet"]
        return VideoStats(
            youtube_id=item["id"], title=snippet.get("title", ""),
            published_at=datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")),
            duration_s=duration, views=_int(stats.get("viewCount")), likes=_int(stats.get("likeCount")),
            comments=_int(stats.get("commentCount")), from_app=item["id"] in app_ids)
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        log.warning("Skipping a video YouTube described oddly: %s", exc)
        return None


def _public_videos(youtube: Any, playlist: str, app_ids: set[str]) -> list[VideoStats]:
    listed = _data(lambda: youtube.playlistItems().list(part="contentDetails", playlistId=playlist,
                                                        maxResults=MAX_VIDEOS))
    ids = [item.get("contentDetails", {}).get("videoId") for item in listed.get("items", [])]
    ids = [i for i in ids if i]
    if not ids:
        return []
    found = _data(lambda: youtube.videos().list(part="snippet,statistics,contentDetails,status", id=",".join(ids)))
    videos = [v for v in (_video_from(item, app_ids) for item in found.get("items", [])) if v]
    return sorted(videos, key=lambda v: v.published_at, reverse=True)


def _rows(answer: dict[str, Any]) -> list[dict[str, Any]]:
    names = [h["name"] for h in answer.get("columnHeaders", [])]
    return [dict(zip(names, row)) for row in answer.get("rows") or []]


def _report(analytics: Any, **query: Any) -> list[dict[str, Any]]:
    return _rows(analytics.reports().query(ids="channel==MINE", **query).execute())


def _unknown_engaged(exc: HttpError) -> bool:
    """engagedViews is the newest metric: an API that does not know it refuses the whole query."""
    return getattr(exc.resp, "status", None) == 400 and "engagedViews" in _message(exc)


def _per_video(analytics: Any, videos: list[VideoStats], today: date) -> list[VideoStats]:
    if not videos:
        return videos
    # Analytics days are US Pacific: start a day early so the oldest video's first day is counted
    start = (min(v.published_at for v in videos).date() - timedelta(days=1)).isoformat()
    query = dict(startDate=start, endDate=today.isoformat(), dimensions="video", sort="-views",
                 maxResults=MAX_VIDEOS, filters="video==" + ",".join(v.youtube_id for v in videos))
    try:
        rows = _report(analytics, metrics=",".join(VIDEO_METRICS), **query)
    except HttpError as exc:
        if not _unknown_engaged(exc):
            raise
        rows = _report(analytics, metrics=",".join(m for m in VIDEO_METRICS if m != "engagedViews"), **query)
    by_id = {row["video"]: row for row in rows}
    return [_with_analytics(v, by_id.get(v.youtube_id)) for v in videos]


def _with_analytics(video: VideoStats, row: dict[str, Any] | None) -> VideoStats:
    if row is None:
        return video
    def num(name: str, kind: type) -> Any:
        return kind(row[name]) if row.get(name) is not None else None

    return replace(video, engaged_views=num("engagedViews", int), analytics_views=num("views", int),
                   avg_view_pct=num("averageViewPercentage", float),
                   avg_view_s=num("averageViewDuration", float), subs_gained=num("subscribersGained", int),
                   shares=num("shares", int))


def _daily(analytics: Any, today: date) -> tuple[DayStats, ...]:
    rows = _report(analytics, startDate=(today - timedelta(days=DAYS_BACK)).isoformat(),
                   endDate=(today - timedelta(days=1)).isoformat(), dimensions="day", sort="day",
                   metrics="views,subscribersGained,estimatedMinutesWatched")
    return tuple(DayStats(day=date.fromisoformat(r["day"]), views=_int(r.get("views")),
                          subs_gained=_int(r.get("subscribersGained")),
                          minutes_watched=float(r.get("estimatedMinutesWatched") or 0)) for r in rows)


def _by_content_type(analytics: Any, metric: str, days: int, today: date) -> dict[str, float]:
    rows = _report(analytics, startDate=(today - timedelta(days=days)).isoformat(), endDate=today.isoformat(),
                   dimensions="creatorContentType", metrics=metric)
    return {str(r["creatorContentType"]).lower().replace("_", ""): float(r.get(metric) or 0) for r in rows}


def _partner_totals(analytics: Any, today: date) -> tuple[int, float]:
    """Partner Program counts engaged Shorts views over 90 days and long-video watch hours over 12 months."""
    try:
        shorts = _by_content_type(analytics, "engagedViews", 90, today).get("shorts", 0)
    except HttpError as exc:
        if not _unknown_engaged(exc):
            raise
        shorts = _by_content_type(analytics, "views", 90, today).get("shorts", 0)  # a little higher than YouTube's
    minutes = _by_content_type(analytics, "estimatedMinutesWatched", 365, today).get("videoondemand", 0)
    return int(shorts), round(minutes / 60, 1)


def fetch_snapshot(youtube: Any, analytics: Any | None, *, app_ids: set[str], now: datetime,
                   analytics_note: str = "") -> Snapshot:
    """The channel's numbers now. Raises ChannelFetchError only when the basic numbers are unavailable."""
    channels = _data(lambda: youtube.channels().list(part="statistics,contentDetails", mine=True)).get("items", [])
    if not channels:
        raise ChannelFetchError("this YouTube account has no channel")
    try:
        stats = channels[0].get("statistics", {})
        playlist = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ChannelFetchError(f"YouTube described the channel oddly (missing {exc})") from exc
    videos = _public_videos(youtube, playlist, app_ids)
    snapshot = Snapshot(taken_at=now.astimezone(UTC), subscribers=_int(stats.get("subscriberCount")),
                        total_views=_int(stats.get("viewCount")), video_count=_int(stats.get("videoCount")),
                        videos=tuple(videos), analytics_note=analytics_note)
    if analytics is None:
        return snapshot
    return _add_analytics(snapshot, analytics, videos, now.astimezone(UTC).date())


def _attempt(what: str, job: Callable[[], Any], notes: list[str]) -> Any:
    """One Analytics report; a refusal is noted and the others still come."""
    try:
        return job()
    except HttpError as exc:
        notes.append(f"{what}: YouTube refused ({_message(exc)})")
    except (*_NETWORK_ERRORS, KeyError, ValueError, TypeError) as exc:
        notes.append(f"{what}: could not be read ({exc})")
    log.warning("YouTube Analytics, %s", notes[-1])
    return None


def _add_analytics(snapshot: Snapshot, analytics: Any, videos: list[VideoStats], today: date) -> Snapshot:
    notes: list[str] = []
    partner = _attempt("Partner Program totals", lambda: _partner_totals(analytics, today), notes)
    per_video = _attempt("per-video numbers", lambda: _per_video(analytics, videos, today), notes)
    daily = _attempt("daily numbers", lambda: _daily(analytics, today), notes)
    return replace(snapshot, videos=tuple(per_video) if per_video is not None else snapshot.videos,
                   days=daily or (), shorts_views_90d=partner[0] if partner else None,
                   long_hours_365d=partner[1] if partner else None, analytics_note="; ".join(notes))
