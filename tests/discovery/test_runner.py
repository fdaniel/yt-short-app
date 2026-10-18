import fcntl
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx

from shorts.config import DiscoverySettings, FeedSource
from shorts.discovery.runner import RunLocked, run_once
from shorts.discovery.triage import Triage, TriageBatch
from shorts.llm.base import AllProvidersExhausted
from shorts.models import TopicStatus, VideoFormat, VideoStatus
from shorts.pipeline import PipelineDeps, PipelineError, VideoResult
from shorts.storage.repositories import VideoRepository
from tests.discovery.items import NOW
from tests.fakes import FakeTTS, ScriptedLLM
from tests.test_pipeline_e2e import ALL_OK, GOOD

FIXTURES = Path(__file__).parent.parent / "fixtures"
HW = FeedSource(name="NVIDIA Blog", url="https://blogs.nvidia.com/feed/", topic="hardware")
GAMES = FeedSource(name="Xbox Wire", url="https://news.xbox.com/en-us/feed/", topic="gaming")
PARA = "<p>" + "Official details about the launch, the date, the price and the platforms are below. " * 8 + "</p>"
GB = 1024**3


def rss(*entries, full_text=True):
    content = f"<content:encoded><![CDATA[{PARA}]]></content:encoded>" if full_text else ""
    items = "".join(f"<item><title>{t}</title><link>{u}</link><pubDate>{d}</pubDate>{content}</item>" for t, u, d in entries)
    return ('<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            f"<channel><title>x</title>{items}</channel></rss>")


HW_ITEMS = [
    ("DLSS 4.5 controls arrive on GeForce NOW", "https://blogs.nvidia.com/blog/dlss-45/", "Sun, 18 Oct 2026 10:00:00 +0000"),
    ("NVIDIA partners with a carmaker", "https://blogs.nvidia.com/blog/cars/", "Sun, 18 Oct 2026 09:00:00 +0000"),
]
GAME_ITEMS = [
    ("Modern Warfare 4 launches October 23", "https://news.xbox.com/en-us/mw4/", "Sun, 18 Oct 2026 08:00:00 +0000"),
]


def verdict(index, interest, game=None):
    return Triage(index=index, interest=interest, rumour_or_leak=False, on_topic=True, game_title=game,
                  format=VideoFormat.NEWS_FLASH, reason=f"interest {interest}")


@pytest.fixture
def cfg(settings):
    return settings.model_copy(update={"discovery": DiscoverySettings(feeds=(HW, GAMES))})


def mock_feeds(hw=HW_ITEMS, games=GAME_ITEMS):
    respx.get(HW.url).respond(200, text=rss(*hw))
    respx.get(GAMES.url).respond(200, text=rss(*games))
    respx.get(url__startswith="https://store.steampowered.com/api/storesearch/").respond(
        200, json=json.loads((FIXTURES / "steam_search_mw4.json").read_text()))


class FakeMake:
    """Stands in for make_video: records calls, can fail per call."""

    def __init__(self, conn, failures=()):
        self.conn, self.failures, self.calls = conn, list(failures), []

    def __call__(self, url, steam_id, fmt, settings, deps, conn, *, article=None):
        self.calls.append((url, steam_id, article))
        video_id = VideoRepository(conn).create(url, steam_id, fmt)
        if self.failures:
            error = self.failures.pop(0)
            if error is not None:
                VideoRepository(conn).set_status(video_id, VideoStatus.FAILED, str(error))
                raise PipelineError(str(error)) from error
        return VideoResult(video_id, Path(f"/x/{video_id}.mp4"), Path("/x/m.json"))


def deps(llm):
    return PipelineDeps(httpx.Client(), llm, FakeTTS(rate=0.07))


def run(cfg, conn, llm, make, *, free=100 * GB, now=NOW):
    return run_once(cfg, deps(llm), conn, now=now, free_bytes=lambda _: free, make=make)


@respx.mock
def test_makes_one_video_from_best_topic_end_to_end(cfg, conn):
    # no full text in the feed: the page is fetched, as for the AMD and NVIDIA newsroom feeds
    respx.get(HW.url).respond(200, text=rss(*HW_ITEMS[:1], full_text=False))
    respx.get(GAMES.url).respond(200, text=rss())
    respx.get(HW_ITEMS[0][1]).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    from shorts.pipeline import make_video
    llm = ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9)]), GOOD, ALL_OK])
    report = run_once(cfg, deps(llm), conn, now=NOW, free_bytes=lambda _: 100 * GB, make=make_video)
    assert len(report.made) == 1 and report.made[0].video_path.exists()
    row = conn.execute("SELECT status, video_id, explanation FROM topics").fetchone()
    assert row["status"] == "made" and row["video_id"] == report.made[0].video_id and "interest" in row["explanation"]


@respx.mock
def test_best_topic_wins_and_feed_text_is_used(cfg, conn):
    mock_feeds()
    make = FakeMake(conn)
    llm = ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9), verdict(1, 3), verdict(2, 5)])])
    report = run(cfg, conn, llm, make)
    assert [c[0] for c in make.calls] == ["https://blogs.nvidia.com/blog/dlss-45/"]
    assert make.calls[0][2] is not None and "launch" in make.calls[0][2].text
    assert len(report.made) == 1 and report.considered == 3


@respx.mock
def test_second_run_does_not_redo_same_story(cfg, conn):
    mock_feeds(hw=HW_ITEMS[:1], games=[])
    make = FakeMake(conn)
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9)])]), make)
    llm = ScriptedLLM([])
    report = run(cfg, conn, llm, make, now=NOW + timedelta(hours=3))
    assert len(make.calls) == 1 and llm.calls == 0 and report.skipped_reason == "nothing new"


@respx.mock
def test_daily_cap(cfg, conn):
    mock_feeds()
    for _ in range(3):
        VideoRepository(conn).create("https://x", None, VideoFormat.NEWS_FLASH)
    conn.execute("UPDATE videos SET created_at = ?", (NOW.isoformat(),))
    llm = ScriptedLLM([])
    report = run(cfg, conn, llm, FakeMake(conn))
    assert report.skipped_reason == "daily limit reached" and llm.calls == 0


@respx.mock
def test_low_disk(cfg, conn):
    mock_feeds()
    report = run(cfg, conn, ScriptedLLM([]), FakeMake(conn), free=1 * GB)
    assert report.skipped_reason == "low disk space"


def test_overlapping_run_refused(cfg, conn):
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.data_dir / "run.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RunLocked):
            run(cfg, conn, ScriptedLLM([]), FakeMake(conn))


@respx.mock
def test_nothing_good(cfg, conn):
    mock_feeds()
    make = FakeMake(conn)
    report = run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 1), verdict(1, 2), verdict(2, 0)])]), make)
    assert report.skipped_reason == "nothing worth a video" and make.calls == []
    statuses = {r["status"] for r in conn.execute("SELECT status FROM topics")}
    assert statuses == {"skipped"}


@respx.mock
def test_failed_story_falls_through_to_next(cfg, conn):
    mock_feeds()
    make = FakeMake(conn, failures=[ValueError("script rejected"), None])
    report = run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9), verdict(1, 3), verdict(2, 8)])]), make)
    assert [c[0] for c in make.calls] == ["https://blogs.nvidia.com/blog/dlss-45/", "https://news.xbox.com/en-us/mw4/"]
    assert len(report.made) == 1
    status = dict(conn.execute("SELECT url, status FROM topics").fetchall())
    assert status["https://blogs.nvidia.com/blog/dlss-45/"] == "failed"


@respx.mock
def test_quota_exhausted_while_making_stops_quietly_and_story_is_retried_later(cfg, conn):
    mock_feeds(hw=HW_ITEMS[:1], games=[])
    make = FakeMake(conn, failures=[AllProvidersExhausted("quota")])
    report = run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9)])]), make)
    assert report.made == () and "AI" in report.skipped_reason
    assert "https://blogs.nvidia.com/blog/dlss-45/" not in {r[0] for r in conn.execute("SELECT url FROM topics")}


@respx.mock
def test_quota_exhausted_during_rating(cfg, conn):
    mock_feeds()

    class Exhausted:
        name = "x"

        def generate_json(self, prompt, schema):
            raise AllProvidersExhausted("quota")

    report = run(cfg, conn, Exhausted(), FakeMake(conn))
    assert "AI" in report.skipped_reason and report.made == ()


@respx.mock
def test_game_story_gets_steam_id(cfg, conn):
    mock_feeds(hw=[], games=GAME_ITEMS)
    make = FakeMake(conn)
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, game="Modern Warfare 4")])]), make)
    assert make.calls[0][1] == 4435490
