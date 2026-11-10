"""Snapshots of the channel kept in the app's database, so the watcher can show changes over days."""

import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from shorts.channel.models import Snapshot

log = logging.getLogger(__name__)

class SnapshotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn  # the table comes from the database migrations

    def save(self, snapshot: Snapshot) -> None:
        self._conn.execute("INSERT INTO channel_snapshots (taken_at, data) VALUES (?, ?)",
                           (snapshot.taken_at.astimezone(UTC).isoformat(), snapshot.to_json()))
        self._conn.commit()

    def _read(self, rows: list[sqlite3.Row]) -> list[Snapshot]:
        snapshots = []
        for row in rows:
            try:
                snapshots.append(Snapshot.from_json(row["data"]))
            except (ValueError, KeyError, TypeError) as exc:
                log.warning("Skipping damaged channel snapshot #%s: %s", row["id"], exc)
        return snapshots

    def latest(self) -> Snapshot | None:
        rows = self._conn.execute("SELECT id, data FROM channel_snapshots ORDER BY taken_at DESC LIMIT 5").fetchall()
        found = self._read(rows)
        return found[0] if found else None

    def history(self, days: int, now: datetime | None = None) -> list[Snapshot]:
        since = ((now or datetime.now(UTC)) - timedelta(days=days)).astimezone(UTC).isoformat()
        rows = self._conn.execute("SELECT id, data FROM channel_snapshots WHERE taken_at >= ? ORDER BY taken_at",
                                  (since,)).fetchall()
        return self._read(rows)

    def prune(self, keep_days: int, now: datetime | None = None) -> None:
        """Keep only the last snapshot of each day, and nothing older than `keep_days`."""
        since = ((now or datetime.now(UTC)) - timedelta(days=keep_days)).astimezone(UTC).isoformat()
        self._conn.execute("DELETE FROM channel_snapshots WHERE taken_at < ?", (since,))
        self._conn.execute(
            "DELETE FROM channel_snapshots WHERE id NOT IN ("
            " SELECT id FROM channel_snapshots AS s WHERE taken_at = ("
            "  SELECT max(taken_at) FROM channel_snapshots WHERE substr(taken_at, 1, 10) = substr(s.taken_at, 1, 10)))")
        self._conn.commit()
