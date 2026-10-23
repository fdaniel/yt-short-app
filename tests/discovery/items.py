from datetime import UTC, datetime, timedelta

from shorts.discovery.feeds import FeedItem

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def item(title: str, *, source: str = "NVIDIA Blog", topic: str = "hardware", hours_old: float = 2,
         url: str | None = None, content: str = "", summary: str = "") -> FeedItem:
    slug = "-".join(title.lower().split())[:60]
    return FeedItem(source, topic, title, url or f"https://{source.replace(' ', '').lower()}.com/{slug}",
                    NOW - timedelta(hours=hours_old), content, summary)
