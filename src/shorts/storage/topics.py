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

    def latest(self, n: int) -> list[sqlite3.Row]:
        """The `n` most recently recorded topics, newest first (status, score, title, source, explanation)."""
        return self._conn.execute(
            "SELECT status, score, title, source, explanation, created_at FROM topics ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()

    def for_video(self, video_id: int) -> sqlite3.Row | None:
        """The story a video was made from (source, score, explanation), if it came from automatic mode."""
        return self._conn.execute(
            "SELECT source, score, explanation FROM topics WHERE video_id = ? ORDER BY id DESC LIMIT 1", (video_id,)
        ).fetchone()

    def forget(self, url: str) -> None:
        """Drop a topic so a later run can consider it again (e.g. the AI quota ran out mid-video)."""
        with self._conn:
            self._conn.execute("DELETE FROM topics WHERE url = ?", (url,))

    def recent_titles(self, days: int, now: datetime) -> list[str]:
        """Titles of stories picked or made, and of videos made, in the last `days` days."""
        since = (now - timedelta(days=days)).isoformat()
        topics = self._conn.execute(
            "SELECT title FROM topics WHERE status IN (?, ?) AND created_at >= ?",
            (TopicStatus.PICKED.value, TopicStatus.MADE.value, since),
        )
        videos = self._conn.execute("SELECT title FROM videos WHERE title IS NOT NULL AND created_at >= ?", (since,))
        return [row[0] for row in topics] + [row[0] for row in videos]

    def videos_made_on(self, day: date, *, game: bool | None = None) -> int:
        """Videos started on `day` (local time) that did not fail; only game (Steam) or only other news if `game` is set."""
        rows = self._conn.execute("SELECT created_at, steam_app_id FROM videos WHERE status != ?",
                                  (VideoStatus.FAILED.value,))
        return sum(1 for created, steam in rows
                   if datetime.fromisoformat(created).astimezone().date() == day
                   and (game is None or (steam is not None) == game))
