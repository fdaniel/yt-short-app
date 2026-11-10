"""One reading of the channel's numbers, as YouTube reported them at a moment."""

import json
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from typing import Any

SHORT_MAX_S = 180  # YouTube treats vertical videos up to three minutes as Shorts


@dataclass(frozen=True)
class VideoStats:
    youtube_id: str
    title: str
    published_at: datetime
    duration_s: int
    views: int
    likes: int
    comments: int
    from_app: bool = False  # made and published by this app (news); otherwise the owner's own upload
    engaged_views: int | None = None  # views that kept watching past the first seconds (YouTube Analytics)
    analytics_views: int | None = None  # views as YouTube Analytics counted them, days behind `views`
    avg_view_pct: float | None = None
    avg_view_s: float | None = None
    subs_gained: int | None = None
    shares: int | None = None

    @property
    def is_short(self) -> bool:
        return self.duration_s <= SHORT_MAX_S

    @property
    def stayed(self) -> float | None:
        """Share of views where people kept watching (engaged views), both counted by YouTube Analytics:
        the live view count runs days ahead of Analytics and would make new Shorts look bad."""
        if self.engaged_views is None or not self.analytics_views:
            return None
        return round(self.engaged_views / self.analytics_views, 4)

    def age_days(self, now: datetime) -> float:
        return (now - self.published_at).total_seconds() / 86400


@dataclass(frozen=True)
class DayStats:
    day: date
    views: int
    subs_gained: int
    minutes_watched: float


@dataclass(frozen=True)
class Snapshot:
    taken_at: datetime
    subscribers: int
    total_views: int
    video_count: int
    videos: tuple[VideoStats, ...]
    days: tuple[DayStats, ...] = ()
    shorts_views_90d: int | None = None
    long_hours_365d: float | None = None
    analytics_note: str = ""  # why the YouTube Analytics numbers are missing; empty when they are there

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=_encode)

    @classmethod
    def from_json(cls, text: str) -> "Snapshot":
        data = json.loads(text)
        return cls(
            **{**data,
               "taken_at": datetime.fromisoformat(data["taken_at"]),
               "videos": tuple(_video(v) for v in data["videos"]),
               "days": tuple(DayStats(**{**d, "day": date.fromisoformat(d["day"])}) for d in data.get("days", []))},
        )


def _encode(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"cannot store {type(value).__name__}")


def _video(data: dict[str, Any]) -> VideoStats:
    known = {f.name for f in fields(VideoStats)}
    clean = {k: v for k, v in data.items() if k in known}
    return VideoStats(**{**clean, "published_at": datetime.fromisoformat(clean["published_at"])})
