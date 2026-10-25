"""One unattended run: find fresh official news, pick the best story, make its video."""

import fcntl
import logging
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from shorts.config import Settings
from shorts.discovery.feeds import FeedItem, article_from_item, fetch_all
from shorts.discovery.score import ScoredTopic, cheap_filter, coverage, fair_share, score_topic
from shorts.discovery.steam_news import fetch_steam_news
from shorts.discovery.triage import story_text, triage
from shorts.llm.base import AllProvidersExhausted, InvalidOutput
from shorts.models import TopicStatus
from shorts.pipeline import PipelineDeps, PipelineError, VideoResult, make_video
from shorts.sources.steam import find_steam_app_id, normalise_title
from shorts.storage.topics import TopicRepository

log = logging.getLogger(__name__)
GB = 1024**3
AI_UNAVAILABLE = "AI unavailable (free quota used up or errors), trying again next run"


class RunLocked(Exception):
    """Another run is still working."""


@dataclass(frozen=True)
class RunReport:
    made: tuple[VideoResult, ...]
    skipped_reason: str | None
    considered: int


@contextmanager
def _run_lock(data_dir: Path) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "run.lock", "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunLocked("another run is still working") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run_once(
    settings: Settings,
    deps: PipelineDeps,
    conn: sqlite3.Connection,
    *,
    now: datetime,
    free_bytes: Callable[[Path], int] = lambda p: shutil.disk_usage(p).free,
    make: Callable[..., VideoResult] = make_video,
) -> RunReport:
    with _run_lock(settings.data_dir):
        return _run(settings, deps, conn, now, free_bytes, make)


def _run(settings, deps, conn, now, free_bytes, make) -> RunReport:
    d = settings.discovery
    topics = TopicRepository(conn)
    today = now.astimezone().date()
    if topics.videos_made_on(today) >= d.max_videos_per_day:
        return RunReport((), "daily limit reached", 0)
    if free_bytes(settings.data_dir) < d.min_free_gb * GB:
        return RunReport((), "low disk space", 0)

    items = fetch_all(deps.http, d.feeds, max_bytes=settings.limits.max_html_bytes)
    items += fetch_steam_news(deps.http, d, since=now - timedelta(hours=d.max_age_h),
                              max_bytes=settings.limits.max_html_bytes)
    recent = topics.recent_titles(d.history_days, now)
    kept, rejected = cheap_filter(items, seen_urls=topics.seen_urls(), recent_titles=recent, settings=d, now=now)
    for it, reason in rejected:
        if reason != "already seen":
            topics.record(it.url, it.source, it.title, it.published, TopicStatus.SKIPPED, None, reason)
    if not kept:
        return RunReport((), "nothing new", len(items))
    try:
        ranked = _rank(fair_share(kept, d.triage_batch), items, recent, settings, deps, topics, now)
    except (AllProvidersExhausted, InvalidOutput) as exc:
        log.warning("Rating stories failed: %s", exc)
        return RunReport((), AI_UNAVAILABLE, len(items))
    if not ranked:
        return RunReport((), "nothing worth a video", len(items))
    return _make_best(ranked, settings, deps, conn, topics, today, make, len(items))


def _mentions(it: FeedItem, game_title: str) -> bool:
    """The story itself names the game (full title, or the part after "Series:"), so footage can't be invented."""
    text = normalise_title(f"{it.title} {story_text(it)}")
    names = {normalise_title(game_title), normalise_title(game_title.split(":", 1)[-1])}
    return any(name and f" {name} " in f" {text} " for name in names)


def _steam_id(it: FeedItem, game_title: str | None, deps: PipelineDeps) -> int | None:
    if it.steam_app_id is not None:
        return it.steam_app_id  # posted on the game's own Steam page
    if not game_title:
        # press release feeds title a story with just the game's name: an exact store match is that game
        return find_steam_app_id(deps.http, it.title) if it.topic == "gaming" else None
    if not _mentions(it, game_title):
        log.warning("AI named game %r but the story does not mention it; no footage", game_title)
        return None
    return find_steam_app_id(deps.http, game_title)


def _rank(batch: list[FeedItem], items: list[FeedItem], recent: list[str], settings: Settings,
          deps: PipelineDeps, topics: TopicRepository, now: datetime) -> list[ScoredTopic]:
    """Scored topics at or above min_score, best first; the rest are recorded as skipped."""
    d = settings.discovery
    ranked = []
    for index, verdict in triage(batch, deps.llm, recent).items():
        it = batch[index]
        steam_id = _steam_id(it, verdict.game_title, deps)
        # tech news shows the official article's own photos, game news its Steam trailer and screenshots
        footage = steam_id is not None or it.topic == "hardware"
        scored = score_topic(it, verdict, footage=footage, coverage=coverage(it, items, d),
                             settings=d, now=now)
        if scored.score < d.min_score:
            topics.record(it.url, it.source, it.title, it.published, TopicStatus.SKIPPED, scored.score,
                          f"below {d.min_score:g}: {scored.explanation}")
        else:
            ranked.append((scored, steam_id))
    ranked.sort(key=lambda pair: pair[0].score, reverse=True)
    return ranked


def _next_pick(pending: list, games: int, others: int):
    """The best story of the kind (game or tech) with fewer videos today, so the channel mixes both;
    the best of any kind when the two are even or the other kind has nothing worth a video."""
    if games != others:
        wanted = next((pair for pair in pending if (pair[1] is not None) == (games < others)), None)
        if wanted:
            return wanted
    return pending[0]


def _make_best(ranked, settings, deps, conn, topics, today, make, considered) -> RunReport:
    d = settings.discovery
    made: list[VideoResult] = []
    pending = list(ranked[: d.max_attempts_per_run])
    games, others = topics.videos_made_on(today, game=True), topics.videos_made_on(today, game=False)
    while pending:
        if len(made) >= d.videos_per_run or topics.videos_made_on(today) >= d.max_videos_per_day:
            break
        scored, steam_id = pick = _next_pick(pending, games, others)
        pending.remove(pick)
        it = scored.item
        topic_id = topics.record(it.url, it.source, it.title, it.published, TopicStatus.PICKED, scored.score,
                                 scored.explanation)
        try:
            result = make(it.url, steam_id, scored.triage.format, settings, deps, conn, article=article_from_item(it))
        except PipelineError as exc:
            if isinstance(exc.__cause__, AllProvidersExhausted):
                topics.forget(it.url)
                return RunReport(tuple(made), AI_UNAVAILABLE, considered)
            log.warning("Story failed, trying the next one: %s (%s)", it.title, exc)
            topics.link_video(topic_id, None, TopicStatus.FAILED)
            continue
        topics.link_video(topic_id, result.video_id, TopicStatus.MADE)
        made.append(result)
        games, others = (games + 1, others) if steam_id is not None else (games, others + 1)
    return RunReport(tuple(made), None if made else "every picked story failed", considered)
