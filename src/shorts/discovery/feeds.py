"""Official RSS/Atom feeds: the only place automatic mode looks for news."""

import calendar
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import feedparser
import httpx

from shorts.config import FeedSource
from shorts.net import DownloadTooLarge, UnsafeURLError, fetch_text
from shorts.sources.article import Article, SourceTextError, extract_article

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedItem:
    source: str
    topic: str
    title: str
    url: str
    published: datetime  # timezone-aware, UTC
    content_html: str  # full text from content:encoded, or "" when the feed only has a summary


def _published(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(parsed), UTC) if parsed else None


def _item(entry, source: FeedSource) -> FeedItem | None:
    title = " ".join((entry.get("title") or "").split())
    url = (entry.get("link") or "").strip()
    published = _published(entry)
    if not (title and url and published):
        return None
    content = "".join(part.get("value", "") for part in entry.get("content", []))
    return FeedItem(source.name, source.topic, title, url, published, content)


def fetch_feed(client: httpx.Client, source: FeedSource, *, max_bytes: int) -> list[FeedItem]:
    parsed = feedparser.parse(fetch_text(client, source.url, max_bytes=max_bytes))
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"{source.name} did not return a readable feed: {parsed.get('bozo_exception')}")
    items = [_item(entry, source) for entry in parsed.entries]
    return [item for item in items if item is not None]


def fetch_all(client: httpx.Client, sources: tuple[FeedSource, ...] | list[FeedSource], *, max_bytes: int) -> list[FeedItem]:
    """Items from every feed that works; a broken feed is logged and skipped."""
    items: list[FeedItem] = []
    for source in sources:
        try:
            items += fetch_feed(client, source, max_bytes=max_bytes)
        except (httpx.HTTPError, ValueError, DownloadTooLarge, UnsafeURLError) as exc:
            log.warning("Skipping feed %s: %s", source.name, exc)
    return items


def article_from_item(item: FeedItem) -> Article | None:
    """The article built from the feed's own full text, or None if the page must be fetched."""
    if not item.content_html:
        return None
    try:
        article = extract_article(item.url, item.content_html)
    except SourceTextError:
        return None
    return replace(article, title=item.title)
