"""Plain advice from a snapshot: which videos worked, why the weak ones failed, and what the plan wants next.

Rules, not guesses: each line names the number behind it, so the owner can check it in YouTube Studio.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from statistics import median
from typing import Literal

from shorts.channel.models import Snapshot, VideoStats
from shorts.channel.plan import YPP_RULES_CHANGE, Checkpoint, PlanWeek, next_checkpoint, plan_week

Grade = Literal["top", "ok", "weak", "early"]
Level = Literal["good", "warn", "bad"]

TOO_EARLY_DAYS = 2  # Shorts keep growing for about two days before they can be compared
TOP, WEAK = 1.5, 0.5  # times the median views of the same kind
MIN_PEERS = 3
RECENT_SHORTS = 20
STAYED_AIM = 0.70  # the plan's "viewed" goal; under 60% the opening is the problem
STAYED_LOW = 0.60
WATCHED_LOW = 50.0  # average % of the Short watched
LONG_SHORT_S = 60
OWN_SLOT = range(18, 21)  # the plan: own gameplay at 18-20h
NEWS_SLOT = range(11, 14)  # big-game news at 11-13h
WEEK_DAYS = 7
SLOT_GRACE_MIN = 30  # a few minutes early still counts as on time
SUBS_PER_1000_LOW = 1.0
BIG_SHORT = 5000
PART_TWO_DAYS = 4  # the plan: a winner gets its follow-up the next day, while viewers still remember it


@dataclass(frozen=True)
class Verdict:
    video: VideoStats
    grade: Grade
    compared_to: int  # median views of the videos it was compared with
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tip:
    level: Level
    text: str


@dataclass(frozen=True)
class Target:
    label: str
    current: float | None
    goal: float
    unit: str = ""

    @property
    def share(self) -> float | None:
        return None if self.current is None else min(1.0, self.current / self.goal) if self.goal else 1.0


@dataclass(frozen=True)
class Report:
    snapshot: Snapshot
    verdicts: tuple[Verdict, ...]
    tips: tuple[Tip, ...]
    week: PlanWeek | None
    checkpoint: Checkpoint | None
    targets: tuple[Target, ...]
    partner: tuple[Target, ...]


def _local(video: VideoStats, tz: tzinfo | None) -> datetime:
    return video.published_at.astimezone(tz)


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _reasons(video: VideoStats, tz: tzinfo | None) -> tuple[str, ...]:
    reasons = []
    stayed = video.stayed
    if stayed is not None and stayed < STAYED_LOW:
        reasons.append(f"Only {stayed:.0%} kept watching; the rest swiped away. Put the best moment and a text"
                       " promise in the first second.")
    if video.avg_view_pct is not None and video.avg_view_pct < WATCHED_LOW:
        long_note = (f" At {_clock(video.duration_s)} it is long for a Short: aim for 20-40 s."
                     if video.duration_s > LONG_SHORT_S else " Cut the slow parts.")
        reasons.append(f"Viewers watched only {video.avg_view_pct:.0f}% of it on average.{long_note}")
    posted = _local(video, tz)
    slot, name = (NEWS_SLOT, "11-13h") if video.from_app else (OWN_SLOT, "18-20h")
    nearly = posted + timedelta(minutes=SLOT_GRACE_MIN)
    if posted.hour not in slot and nearly.hour not in slot:
        reasons.append(f"Posted at {posted:%H:%M}; the plan's time for these is {name}.")
    return tuple(reasons)


def grade_videos(snapshot: Snapshot, tz: tzinfo | None = None) -> tuple[Verdict, ...]:
    """Each recent Short against the median of its own kind (the owner's uploads or the app's news)."""
    now = snapshot.taken_at
    shorts = [v for v in snapshot.videos if v.is_short][:RECENT_SHORTS]
    settled = [v for v in shorts if v.age_days(now) >= TOO_EARLY_DAYS]
    verdicts = []
    for video in shorts:
        peers = [p.views for p in settled if p.from_app == video.from_app]
        if len(peers) < MIN_PEERS:
            peers = [p.views for p in settled]
        middle = int(median(peers)) if peers else 0
        if video.age_days(now) < TOO_EARLY_DAYS or not middle:
            grade: Grade = "early" if video.age_days(now) < TOO_EARLY_DAYS else "ok"
        elif video.views >= TOP * middle:
            grade = "top"
        elif video.views <= WEAK * middle:
            grade = "weak"
        else:
            grade = "ok"
        reasons = _reasons(video, tz) if grade in ("weak", "ok") else ()
        verdicts.append(Verdict(video, grade, middle, reasons))
    return tuple(verdicts)


def _subs_per_1000(snapshot: Snapshot) -> float | None:
    views = sum(d.views for d in snapshot.days) if snapshot.days else snapshot.total_views
    subs = sum(d.subs_gained for d in snapshot.days) if snapshot.days else snapshot.subscribers
    return subs * 1000 / views if views else None


def _tips(snapshot: Snapshot, verdicts: tuple[Verdict, ...], tz: tzinfo | None) -> tuple[Tip, ...]:
    now = snapshot.taken_at
    tips: list[Tip] = []
    note = snapshot.analytics_note
    if note:
        how = "" if "youtube-connect" in note else " If this keeps happening, run python -m shorts youtube-connect."
        tips.append(Tip("warn", f"Without YouTube Analytics the watcher cannot see why videos fail: {note}.{how}"))
    week = [v for v in snapshot.videos if v.age_days(now) < WEEK_DAYS]
    own_shorts = [v for v in week if v.is_short and not v.from_app]
    if len(own_shorts) < WEEK_DAYS:
        tips.append(Tip("bad" if len(own_shorts) < 4 else "warn",
                        f"{len(own_shorts)} of your own Shorts in the last 7 days; the plan is one every day at"
                        " 18-20h."))
    if not any(not v.is_short for v in week):
        tips.append(Tip("warn", "No long video in the last 7 days: the plan has one every Saturday (8-15 min)."
                                " Long videos are the only source of watch hours."))
    rate = _subs_per_1000(snapshot)
    if rate is not None and rate < SUBS_PER_1000_LOW:
        tips.append(Tip("bad", f"About {rate:.1f} new subscribers per 1,000 views: viewers watch but do not"
                               " subscribe. End each Short with the next part (\"Part 2 tomorrow\") and keep series"
                               " going."))
    for v in verdicts:
        if v.grade == "top" and not v.video.from_app and v.video.age_days(now) < PART_TWO_DAYS:
            tips.append(Tip("good", f"“{v.video.title}” did well ({v.video.views:,} views, the usual is"
                                    f" {v.compared_to:,}): make part 2 tomorrow."))
    weak = [v for v in verdicts if v.grade == "weak"]
    if weak:
        tips.append(Tip("warn", f"{len(weak)} recent Short{'s' if len(weak) > 1 else ''} well under the usual: see"
                                " why in the list below."))
    return tuple(tips)


def _targets(snapshot: Snapshot, checkpoint: Checkpoint | None) -> tuple[Target, ...]:
    if checkpoint is None:
        return ()
    big = sum(1 for v in snapshot.videos if v.is_short and v.views >= BIG_SHORT)
    recent = snapshot.videos[:RECENT_SHORTS]
    own = round(100 * sum(1 for v in recent if not v.from_app) / len(recent)) if recent else None
    stayed = [v.stayed for v in recent if v.is_short and v.stayed is not None]
    return (
        Target("Subscribers", snapshot.subscribers, checkpoint.subscribers),
        Target("Shorts over 5k views", big, checkpoint.shorts_over_5k),
        Target("Long-video watch hours", snapshot.long_hours_365d, checkpoint.watch_hours, "h"),
        Target("Shorts viewers who kept watching", round(100 * median(stayed)) if stayed else None,
               checkpoint.stayed_pct, "%"),
        Target("Uploads that are your own", own, checkpoint.own_share_pct, "%"),
    )


def _partner(snapshot: Snapshot, today: date) -> tuple[Target, ...]:
    doubled = today >= YPP_RULES_CHANGE
    return (
        Target("Subscribers", snapshot.subscribers, 1000),
        Target("Shorts views (90 days)", snapshot.shorts_views_90d, 20_000_000 if doubled else 10_000_000),
        Target("Long-video watch hours (12 months)", snapshot.long_hours_365d, 8000 if doubled else 4000, "h"),
    )


def build_report(snapshot: Snapshot, tz: tzinfo | None = None, now: datetime | None = None) -> Report:
    """`now` places the plan's week and checkpoint; the snapshot may be a few hours or days old."""
    today = (now or snapshot.taken_at).astimezone(tz).date()
    verdicts = grade_videos(snapshot, tz)
    checkpoint = next_checkpoint(today)
    return Report(snapshot=snapshot, verdicts=verdicts, tips=_tips(snapshot, verdicts, tz), week=plan_week(today),
                  checkpoint=checkpoint, targets=_targets(snapshot, checkpoint), partner=_partner(snapshot, today))
