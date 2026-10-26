import fcntl
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx

from shorts.config import DiscoverySettings, FeedSource
from shorts.discovery.runner import RunLocked, run_once
from shorts.discovery.steam_news import NEWS_FEED_URL
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
PARA = "<p>" + "Official details from Activision about the launch, the date, the price and the platforms. " * 8 + "</p>"
GB = 1024**3


def rss(*entries, full_text=True, summary=""):
    content = f"<content:encoded><![CDATA[{PARA}]]></content:encoded>" if full_text else ""
    content += f"<description><![CDATA[{summary}]]></description>" if summary else ""
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


def verdict(index, interest, game=None, same=False):
    return Triage(index=index, interest=interest, rumour_or_leak=False, on_topic=True, same_story_as_recent=same, game_title=game,
                  format=VideoFormat.NEWS_FLASH, reason=f"interest {interest}")


@pytest.fixture
def cfg(settings):
    return settings.model_copy(update={"discovery": DiscoverySettings(feeds=(HW, GAMES), steam_lists=(), epic_free_games=False)})


def mock_store(name="Call of Duty®: Modern Warfare® 4", developers=("Infinity Ward",), publishers=("Activision",)):
    respx.get(url__startswith="https://store.steampowered.com/api/storesearch/").respond(
        200, json=json.loads((FIXTURES / "steam_search_mw4.json").read_text()))
    respx.get(url__startswith="https://store.steampowered.com/api/appdetails").respond(200, json={"4435490": {
        "success": True, "data": {"name": name, "developers": list(developers), "publishers": list(publishers)}}})


def mock_feeds(hw=HW_ITEMS, games=GAME_ITEMS):
    respx.get(HW.url).respond(200, text=rss(*hw))
    respx.get(GAMES.url).respond(200, text=rss(*games))
    mock_store()


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
def test_makes_one_video_from_best_topic_end_to_end(cfg, conn, synthetic_video):
    # no full text in the feed: the page is fetched, as for the AMD and NVIDIA newsroom feeds
    respx.get(HW.url).respond(200, text=rss(*HW_ITEMS[:1], full_text=False))
    respx.get(GAMES.url).respond(200, text=rss())
    respx.get(HW_ITEMS[0][1]).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    from shorts.pipeline import make_video
    from tests.test_pipeline_e2e import mock_pexels

    mock_pexels(synthetic_video)  # hardware news has no game trailer: its footage is stock video
    llm = ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9)]), GOOD, ALL_OK])
    cfg = cfg.model_copy(update={"pexels_api_key": "pk"})
    report = run_once(cfg, deps(llm), conn, now=NOW, free_bytes=lambda _: 100 * GB, make=make_video)
    assert len(report.made) == 1 and report.made[0].video_path.exists()
    row = conn.execute("SELECT status, video_id, explanation FROM topics").fetchone()
    assert row["status"] == "made" and row["video_id"] == report.made[0].video_id and "interest" in row["explanation"]


@respx.mock
def test_best_topic_wins_and_feed_text_is_used(cfg, conn):
    mock_feeds()
    make = FakeMake(conn)
    llm = ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9), verdict(1, 3), verdict(2, 2)])])
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
    for _ in range(cfg.discovery.max_videos_per_day):
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
    # the batch takes each feed in turn: [0] DLSS (NVIDIA), [1] MW4 (Xbox), [2] cars (NVIDIA)
    report = run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9), verdict(1, 8), verdict(2, 3)])]), make)
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


@respx.mock
def test_same_launch_worded_differently_is_not_made_twice(cfg, conn):
    # real titles from 2026-10-16/17: word overlap 0.31, below the cheap duplicate filter
    first = ("NVIDIA RTX Spark PCs Available Today \u2014 A New Beginning for Windows PCs",
             "https://blogs.nvidia.com/blog/rtx-spark-today/", "Sun, 18 Oct 2026 06:00:00 +0000")
    second = ("RTX Spark Ignites Global Celebration as New Windows PCs Arrive",
              "https://blogs.nvidia.com/blog/rtx-spark-celebration/", "Sun, 18 Oct 2026 10:00:00 +0000")
    make = FakeMake(conn)
    mock_feeds(hw=[first], games=[])
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9)])]), make)
    VideoRepository(conn).save_script(1, "{}", "NVIDIA RTX Spark PCs Are Available Today")
    respx.get(HW.url).respond(200, text=rss(first, second))
    llm = ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, same=True)])])
    report = run(cfg, conn, llm, make, now=NOW + timedelta(hours=3))
    assert len(make.calls) == 1 and report.skipped_reason == "nothing worth a video"
    assert "NVIDIA RTX Spark PCs Are Available Today" in llm.prompts[0]


@respx.mock
def test_game_title_not_in_story_gets_no_footage(cfg, conn):
    # the AI names a game the story never mentions: no footage rather than possibly the wrong game's
    story = ("DMZ Early Access Starts October 20", "https://news.xbox.com/en-us/dmz/", "Sun, 18 Oct 2026 08:00:00 +0000")
    mock_feeds(hw=[], games=[story])
    make = FakeMake(conn)
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, game="Call of Duty: Modern Warfare 4")])]), make)
    assert make.calls[0][1] is None


@respx.mock
def test_full_title_from_ai_still_matches_story_that_uses_short_name(cfg, conn):
    mock_feeds(hw=[], games=GAME_ITEMS)  # "Modern Warfare 4 launches October 23"
    make = FakeMake(conn)
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, game="Call of Duty: Modern Warfare 4")])]), make)
    assert make.calls[0][1] == 4435490


@respx.mock
def test_game_named_only_in_the_feed_summary_gets_steam_id(cfg, conn):
    story = ("New trailer", "https://news.xbox.com/en-us/trailer/", "Sun, 18 Oct 2026 08:00:00 +0000")
    respx.get(HW.url).respond(200, text=rss())
    respx.get(GAMES.url).respond(200, text=rss(story, full_text=False,
                                                  summary="<p>Modern Warfare 4 gets a new trailer.</p>"))
    respx.get(story[1]).respond(200, text=f"<html><body><article><h1>New trailer</h1>{PARA}</article></body></html>")
    mock_store()
    make = FakeMake(conn)
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, game="Modern Warfare 4")])]), make)
    assert make.calls[0][1] == 4435490


@respx.mock
def test_press_release_titled_with_the_game_name_gets_steam_id(cfg, conn):
    # GamesPress titles each release with just the game's name; the AI may not repeat it
    story = ("Call of Duty®: Modern Warfare® 4", "https://news.xbox.com/en-us/pr/", "Sun, 18 Oct 2026 08:00:00 +0000")
    mock_feeds(hw=[], games=[story])
    make = FakeMake(conn)
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, game=None)])]), make)
    assert make.calls[0][1] == 4435490


@respx.mock
def test_headline_is_not_taken_for_a_game_name(cfg, conn):
    mock_feeds(hw=[], games=GAME_ITEMS)  # "Modern Warfare 4 launches October 23"
    make = FakeMake(conn)
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, game=None)])]), make)
    assert make.calls[0][1] is None


SEASON = ("Modern Warfare 4 season one detailed", "https://news.xbox.com/en-us/mw4-season/", "Sun, 18 Oct 2026 07:00:00 +0000")


@respx.mock
def test_a_run_mixes_tech_and_games_instead_of_two_games(cfg, conn):
    # batch order: [0] DLSS (tech), [1] MW4 launch, [2] MW4 season; both games rate higher than the tech story
    mock_feeds(hw=HW_ITEMS[:1], games=GAME_ITEMS + [SEASON])
    make = FakeMake(conn)
    llm = ScriptedLLM([TriageBatch(verdicts=[verdict(0, 6), verdict(1, 9, game="Modern Warfare 4"),
                                             verdict(2, 8, game="Modern Warfare 4")])])
    run(cfg, conn, llm, make)
    assert [c[0] for c in make.calls] == ["https://news.xbox.com/en-us/mw4/", "https://blogs.nvidia.com/blog/dlss-45/"]


@respx.mock
def test_a_day_with_more_tech_videos_gets_a_game_next(cfg, conn):
    VideoRepository(conn).create("https://earlier-tech", None, VideoFormat.NEWS_FLASH)
    conn.execute("UPDATE videos SET created_at = ?", (NOW.isoformat(),))
    mock_feeds(hw=HW_ITEMS[:1], games=GAME_ITEMS)
    make = FakeMake(conn)
    llm = ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9), verdict(1, 7, game="Modern Warfare 4")])])
    run(cfg.model_copy(update={"discovery": cfg.discovery.model_copy(update={"videos_per_run": 1})}), conn, llm, make)
    assert [c[0] for c in make.calls] == ["https://news.xbox.com/en-us/mw4/"]


@respx.mock
def test_only_one_kind_available_is_still_made(cfg, conn):
    mock_feeds(hw=[], games=GAME_ITEMS + [SEASON])
    make = FakeMake(conn)
    llm = ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, game="Modern Warfare 4"), verdict(1, 8, game="Modern Warfare 4")])])
    run(cfg, conn, llm, make)
    assert len(make.calls) == 2


@respx.mock
def test_tech_story_counts_its_newsroom_photos_as_footage(cfg, conn):
    mock_feeds(hw=HW_ITEMS[:1], games=[])
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 7)])]), FakeMake(conn))
    explanation = conn.execute("SELECT explanation FROM topics").fetchone()["explanation"]
    assert "footage 1.00" in explanation


@respx.mock
def test_steam_announcement_is_made_with_its_own_game_footage(cfg, conn):
    from tests.discovery.test_steam_news import mock_list, row, steam_rss

    mock_feeds(hw=[], games=[])
    mock_list("topsellers", row(3764200, "Resident Evil Requiem"))
    respx.get(NEWS_FEED_URL.format(app_id=3764200)).respond(200, text=steam_rss(("Free DLC out now", 2)))
    search = respx.get(url__startswith="https://store.steampowered.com/api/storesearch/")
    cfg = cfg.model_copy(update={"discovery": cfg.discovery.model_copy(update={"steam_lists": ("topsellers",)})})
    make = FakeMake(conn)
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 8, game="Resident Evil Requiem")])]), make)
    assert make.calls[0][1] == 3764200 and not search.called
    assert "Resident Evil Requiem: Free DLC out now" in make.calls[0][2].title


@respx.mock
def test_a_store_game_with_the_same_name_from_another_studio_is_not_used(cfg, conn):
    # FragPunk's new "Farlands" mode is not JanduSoft's farming game "Farlands"
    mock_feeds(hw=[], games=GAME_ITEMS)
    mock_store(developers=("JanduSoft",), publishers=("Anotherindie",))
    make = FakeMake(conn)
    report = run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, game="Modern Warfare 4")])]), make)
    assert make.calls == [] and report.made == ()
    reason = conn.execute("SELECT status, explanation FROM topics").fetchone()
    assert reason["status"] == "skipped" and "JanduSoft" in reason["explanation"]


@respx.mock
def test_a_story_whose_page_cannot_be_read_is_set_aside_not_retried_every_run(cfg, conn):
    mock_feeds(hw=[], games=[])
    respx.get(GAMES.url).respond(200, text=rss(*GAME_ITEMS, full_text=False))
    respx.get("https://news.xbox.com/en-us/mw4/").respond(200, text="<html><body><p>Loading...</p></body></html>")
    make = FakeMake(conn)
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, game="Modern Warfare 4")])]), make)
    assert make.calls == []
    reason = conn.execute("SELECT status, explanation FROM topics").fetchone()
    assert reason["status"] == "skipped" and "could not extract enough text" in reason["explanation"]


@respx.mock
def test_a_story_whose_page_times_out_is_tried_again_next_run(cfg, conn):
    mock_feeds(hw=[], games=[])
    respx.get(GAMES.url).respond(200, text=rss(*GAME_ITEMS, full_text=False))
    respx.get("https://news.xbox.com/en-us/mw4/").mock(side_effect=httpx.ReadTimeout("slow"))
    make = FakeMake(conn)
    run(cfg, conn, ScriptedLLM([TriageBatch(verdicts=[verdict(0, 9, game="Modern Warfare 4")])]), make)
    assert make.calls == []
    assert conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 0
