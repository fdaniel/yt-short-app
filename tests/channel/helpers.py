"""Small builders for channel snapshots, so each test states only what it is about."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from shorts.channel.models import DayStats, Snapshot, VideoStats

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def video(n=1, *, views=1000, days_old=5, hour=19, from_app=False, duration_s=40, **extra) -> VideoStats:
    posted = (NOW - timedelta(days=days_old)).replace(hour=hour, minute=30)
    base = VideoStats(youtube_id=f"vid{n:08d}xx", title=f"Video {n}", published_at=posted, duration_s=duration_s,
                      views=views, likes=views // 50, comments=1, from_app=from_app)
    return replace(base, **extra)


def snapshot(*videos: VideoStats, subscribers=13, days=(), **extra) -> Snapshot:
    base = Snapshot(taken_at=NOW, subscribers=subscribers, total_views=sum(v.views for v in videos),
                    video_count=len(videos), videos=tuple(videos), days=tuple(days))
    return replace(base, **extra)


def days(views_per_day: int, subs_per_day: int = 0, count: int = 28) -> tuple[DayStats, ...]:
    end = NOW.date() - timedelta(days=1)
    return tuple(DayStats(day=end - timedelta(days=i), views=views_per_day, subs_gained=subs_per_day,
                          minutes_watched=0.0) for i in reversed(range(count)))


TODAY = date(2026, 11, 10)
