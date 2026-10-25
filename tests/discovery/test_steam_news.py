from datetime import timedelta

import httpx
import respx

from shorts.config import DiscoverySettings
from shorts.discovery.steam_news import LIST_URL, NEWS_FEED_URL, STEAM_SOURCE, announcements, fetch_steam_news, popular_games
from tests.discovery.items import NOW

LOGO = "https://shared.fastly.steamstatic.com/store_item_assets/steam/{kind}/{id}/abc/capsule_sm_120.jpg?t=1"
POST = "<p>" + "Ludra awakens on November 4th with a new region, new bosses and a free event for every player. " * 6 + "</p>"


def row(app_id, name, kind="apps"):
    return {"name": name, "logo": LOGO.format(kind=kind, id=app_id)}


def mock_list(name, *rows, status=200):
    respx.get(url__startswith=LIST_URL, params={"filter": name}).respond(status, json={"items": list(rows)})


def steam_rss(*posts, text=POST):
    items = "".join(f"<item><title>{t}</title><link>https://store.steampowered.com/news/app/1/view/{i}</link>"
                    f"<pubDate>{(NOW - timedelta(hours=h)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
                    f"<description><![CDATA[{text}]]></description></item>" for i, (t, h) in enumerate(posts))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{items}</channel></rss>'


@respx.mock
def test_popular_games_come_from_steam_lists_without_repeats_or_bundles():
    mock_list("popularwishlist", row(4115450, "Phantom Blade Zero"), row(77, "Big Bundle", kind="bundles"))
    mock_list("topsellers", row(1091500, "Cyberpunk 2077"), row(4115450, "Phantom Blade Zero"))
    games = popular_games(httpx.Client(), ("popularwishlist", "topsellers"), 25, max_bytes=1_000_000)
    assert games == {4115450: "Phantom Blade Zero", 1091500: "Cyberpunk 2077"}


@respx.mock
def test_a_broken_list_is_skipped():
    mock_list("popularwishlist", status=500)
    mock_list("topsellers", row(1091500, "Cyberpunk 2077"))
    assert popular_games(httpx.Client(), ("popularwishlist", "topsellers"), 25, max_bytes=1_000_000) == {1091500: "Cyberpunk 2077"}


@respx.mock
def test_recent_posts_name_their_game_and_carry_its_steam_id():
    respx.get(NEWS_FEED_URL.format(app_id=12)).respond(200, text=steam_rss(
        ("Ludra Awakens on November 4th", 3), ("AION 2 Season 2 starts today", 5), ("Old news", 60)))
    items = announcements(httpx.Client(), 12, "AION 2™", since=NOW - timedelta(hours=48), max_bytes=1_000_000)
    assert [it.title for it in items] == ["AION 2: Ludra Awakens on November 4th", "AION 2 Season 2 starts today"]
    it = items[0]
    assert it.steam_app_id == 12 and it.source == STEAM_SOURCE and it.topic == "gaming"
    assert "November 4th" in it.content_html  # the post itself is the story's full text


@respx.mock
def test_a_game_whose_feed_fails_is_skipped():
    mock_list("topsellers", row(1, "Broken Game"), row(2, "Working Game"))
    respx.get(NEWS_FEED_URL.format(app_id=1)).respond(503)
    respx.get(NEWS_FEED_URL.format(app_id=2)).respond(200, text=steam_rss(("Working Game 1.0 is out now", 1)))
    d = DiscoverySettings(steam_lists=("topsellers",))
    items = fetch_steam_news(httpx.Client(), d, since=NOW - timedelta(hours=48), max_bytes=1_000_000)
    assert [(it.title, it.steam_app_id) for it in items] == [("Working Game 1.0 is out now", 2)]


def test_steam_lists_can_be_turned_off():
    assert fetch_steam_news(httpx.Client(), DiscoverySettings(steam_lists=()), since=NOW, max_bytes=1) == []


@respx.mock
def test_a_post_too_short_to_tell_the_story_is_left_out():
    respx.get(NEWS_FEED_URL.format(app_id=12)).respond(200, text=steam_rss(("Watch the new trailer", 1), text="<p>Watch it!</p>"))
    assert announcements(httpx.Client(), 12, "AION 2", since=NOW - timedelta(hours=48), max_bytes=1_000_000) == []
