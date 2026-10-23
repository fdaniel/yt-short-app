from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from shorts.config import FeedSource, load_settings
from shorts.discovery.feeds import FeedItem, article_from_item, fetch_all, fetch_feed

FIXTURES = Path(__file__).parent.parent / "fixtures"
BLOG = FeedSource(name="NVIDIA Blog", url="https://blogs.nvidia.com/feed/", topic="hardware")
AMD = FeedSource(name="AMD Press Releases", url="https://ir.amd.com/rss", topic="hardware")
XBOX = FeedSource(name="Xbox Wire", url="https://news.xbox.com/en-us/feed/", topic="gaming")


def _mock(source: FeedSource, fixture: str) -> None:
    respx.get(source.url).respond(200, text=(FIXTURES / fixture).read_text())


@respx.mock
def test_parses_items_with_full_text():
    _mock(BLOG, "feed_nvidia_blog.xml")
    items = fetch_feed(httpx.Client(), BLOG, max_bytes=1_000_000)
    assert [i.url for i in items] == [
        "https://blogs.nvidia.com/blog/geforce-now-dlss-4-5/",
        "https://blogs.nvidia.com/blog/rtx-spark-celebration/",
    ]
    assert items[0].published == datetime(2026, 10, 16, 13, 0, tzinfo=UTC)
    assert items[0].source == "NVIDIA Blog" and items[0].topic == "hardware"
    assert "DLSS 4.5" in items[0].content_html and items[1].content_html == ""


@respx.mock
def test_cdata_and_entities_cleaned():
    _mock(BLOG, "feed_nvidia_blog.xml")
    titles = [i.title for i in fetch_feed(httpx.Client(), BLOG, max_bytes=1_000_000)]
    assert titles == ["Dial Up the Cloud: NVIDIA DLSS 4.5 Controls Arrive – GeForce NOW", "RTX Spark Ignites Global Celebration"]


@respx.mock
def test_two_digit_year_and_offset_dates():
    _mock(AMD, "feed_amd_ir.xml")
    items = fetch_feed(httpx.Client(), AMD, max_bytes=1_000_000)
    assert items[0].published == datetime(2026, 10, 12, 13, 0, tzinfo=UTC)


@respx.mock
def test_one_broken_feed_does_not_stop_others():
    respx.get(BLOG.url).respond(500)
    respx.get(XBOX.url).respond(200, text="<html><body>Not a feed</body></html>")
    _mock(AMD, "feed_amd_ir.xml")
    items = fetch_all(httpx.Client(), [BLOG, XBOX, AMD], max_bytes=1_000_000)
    assert {i.source for i in items} == {"AMD Press Releases"} and len(items) == 2


@respx.mock
def test_network_error_skips_feed():
    respx.get(BLOG.url).mock(side_effect=httpx.ConnectTimeout("slow"))
    _mock(AMD, "feed_amd_ir.xml")
    assert len(fetch_all(httpx.Client(), [BLOG, AMD], max_bytes=1_000_000)) == 2


@respx.mock
def test_article_from_item_uses_feed_text():
    _mock(BLOG, "feed_nvidia_blog.xml")
    item = fetch_feed(httpx.Client(), BLOG, max_bytes=1_000_000)[0]
    article = article_from_item(item)
    assert article is not None and "150 games" in article.text
    assert article.title == item.title and article.url == item.url and article.domain == "blogs.nvidia.com"


def test_article_from_item_none_when_no_content():
    item = FeedItem("AMD", "hardware", "t", "https://ir.amd.com/x", datetime.now(UTC), "")
    assert article_from_item(item) is None
    short = FeedItem("AMD", "hardware", "t", "https://ir.amd.com/x", datetime.now(UTC), "<p>too short</p>")
    assert article_from_item(short) is None


def test_default_feeds_in_settings(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("")
    d = load_settings(cfg, {"GEMINI_API_KEY": "k"}).discovery
    assert [f.name for f in d.feeds] == ["NVIDIA Newsroom", "NVIDIA Blog", "AMD Press Releases", "Xbox Wire",
                                         "PlayStation Blog", "Nintendo", "GamesPress"]
    assert {f.topic for f in d.feeds[3:]} == {"gaming"}
    assert (d.max_videos_per_day, d.videos_per_run, d.max_attempts_per_run, d.triage_batch) == (6, 2, 4, 15)
    assert (d.max_age_h, d.min_free_gb) == (48, 10)
    assert d.weights.interest == 0.5 and "board of directors" in d.exclude_keywords


def test_article_from_single_paragraph_fragment():
    # trafilatura returns nothing for a bare one-paragraph fragment unless it is wrapped in a page
    text = "Official details about the launch date, the price and every platform are listed here today. " * 6
    it = FeedItem("Xbox Wire", "gaming", "MW4", "https://news.xbox.com/x", datetime.now(UTC), f"<p>{text}</p>")
    article = article_from_item(it)
    assert article is not None and "launch date" in article.text


@respx.mock
def test_feed_body_is_never_opened_as_a_path_or_url(tmp_path):
    local = tmp_path / "secret.xml"
    local.write_text((FIXTURES / "feed_amd_ir.xml").read_text())
    for body in (str(local), f"file://{local}"):
        respx.get(BLOG.url).respond(200, text=body)
        assert fetch_all(httpx.Client(), [BLOG], max_bytes=1_000_000) == []
