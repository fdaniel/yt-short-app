"""Popular games' own Steam announcements: official game news that always has the game's footage."""

import json
import logging
import re
from dataclasses import replace
from datetime import datetime
from urllib.parse import urlencode

import httpx

from shorts.config import DiscoverySettings, FeedSource
from shorts.discovery.feeds import FeedItem, article_from_item, fetch_feed
from shorts.net import DownloadTooLarge, UnsafeURLError, fetch_bytes
from shorts.sources.steam import normalise_title

log = logging.getLogger(__name__)

STEAM_SOURCE = "Steam announcements"
LIST_URL = "https://store.steampowered.com/search/results/?"
# a game's own news feed: only posts by its developer or publisher, never news sites' articles
NEWS_FEED_URL = "https://store.steampowered.com/feeds/news/app/{app_id}/?l=english"
_APP_IN_IMAGE = re.compile(r"/steam/apps/(\d+)/")
_ERRORS = (httpx.HTTPError, ValueError, DownloadTooLarge, UnsafeURLError)


def popular_games(client: httpx.Client, lists: tuple[str, ...], per_list: int, *, max_bytes: int) -> dict[int, str]:
    """{Steam app id: name} from Steam's own store lists (most wishlisted, top sellers...); a broken list is skipped."""
    games: dict[int, str] = {}
    for name in lists:
        query = urlencode({"filter": name, "json": 1, "count": per_list, "cc": "us", "l": "english"})
        try:
            rows = json.loads(fetch_bytes(client, LIST_URL + query, max_bytes=max_bytes)).get("items", [])
        except _ERRORS as exc:
            log.warning("Skipping Steam list %s: %s", name, exc)
            continue
        for row in rows[:per_list]:
            # bundles and packages have no /apps/<id>/ image, so only single games are kept
            found = _APP_IN_IMAGE.search(str(row.get("logo", "")))
            if found and row.get("name"):
                games.setdefault(int(found.group(1)), str(row["name"]))
    return games


def _titled(title: str, game: str) -> str:
    """"Ludra Awakens on November 4th" -> "AION 2: Ludra Awakens on November 4th", so the story names its game."""
    clean = re.sub(r"[™®©]", "", game).strip()
    return title if f" {normalise_title(clean)} " in f" {normalise_title(title)} " else f"{clean}: {title}"


def announcements(client: httpx.Client, app_id: int, game: str, *, since: datetime, max_bytes: int) -> list[FeedItem]:
    """The game's posts since `since`, with the post itself as the story's full text. Steam's news page
    has no readable text, so a post too short to write a video from is left out."""
    source = FeedSource(name=STEAM_SOURCE, url=NEWS_FEED_URL.format(app_id=app_id), topic="gaming")
    posts = [
        replace(it, title=_titled(it.title, game), content_html=it.content_html or it.summary, steam_app_id=app_id)
        for it in fetch_feed(client, source, max_bytes=max_bytes)
        if it.published >= since
    ]
    return [it for it in posts if article_from_item(it) is not None]


def fetch_steam_news(client: httpx.Client, d: DiscoverySettings, *, since: datetime, max_bytes: int) -> list[FeedItem]:
    """Recent announcements of the most popular games; a game whose feed fails is logged and skipped."""
    items: list[FeedItem] = []
    for app_id, game in popular_games(client, d.steam_lists, d.steam_games_per_list, max_bytes=max_bytes).items():
        try:
            items += announcements(client, app_id, game, since=since, max_bytes=max_bytes)
        except _ERRORS as exc:
            log.warning("Skipping Steam news of %s: %s", game, exc)
    return items
