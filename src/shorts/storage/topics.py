"""Data access for news topics: what was seen, skipped, picked and made."""

import sqlite3
from datetime import UTC, date, datetime, timedelta

from shorts.models import TopicStatus, VideoStatus


class TopicRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def seen_urls(self) -> set[str]:
        return {row[0] for row in self._conn.execute("SELECT url FROM topics")}

    def record(
        self,
        url: str,
        source: str,
        title: str,
        published: datetime,
        status: TopicStatus,
        score: float | None,
        explanation: str,
    ) -> int:
        """Insert the topic, or update status/score/explanation if its URL is already known."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO topics (url, source, title, published_at, score, explanation, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(url) DO UPDATE SET status = excluded.status, score = excluded.score,"
                " explanation = excluded.explanation",
                (url, source, title, published.isoformat(), score, explanation, status.value, datetime.now(UTC).isoformat()),
            )
        return self._conn.execute("SELECT id FROM topics WHERE url = ?", (url,)).fetchone()[0]

    def link_video(self, topic_id: int, video_id: int | None, status: TopicStatus) -> None:
        with self._conn:
            self._conn.execute("UPDATE topics SET video_id = ?, status = ? WHERE id = ?", (video_id, status.value, topic_id))

    def recent_titles(self, days: int, now: datetime) -> list[str]:
        """Titles of stories picked or made, and of videos made, in the last `days` days."""
        since = (now - timedelta(days=days)).isoformat()
        topics = self._conn.execute(
            "SELECT title FROM topics WHERE status IN (?, ?) AND created_at >= ?",
            (TopicStatus.PICKED.value, TopicStatus.MADE.value, since),
        )
        videos = self._conn.execute("SELECT title FROM videos WHERE title IS NOT NULL AND created_at >= ?", (since,))
        return [row[0] for row in topics] + [row[0] for row in videos]

    def videos_made_on(self, day: date) -> int:
        """Videos started on `day` (local time) that did not fail."""
        rows = self._conn.execute("SELECT created_at FROM videos WHERE status != ?", (VideoStatus.FAILED.value,))
        return sum(1 for (created,) in rows if datetime.fromisoformat(created).astimezone().date() == day)
