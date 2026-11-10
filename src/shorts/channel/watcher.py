"""Takes the channel's snapshots and turns the latest into a report, for the dashboard and automatic mode."""

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Protocol

from shorts.channel.advice import Report, build_report
from shorts.channel.fetch import ChannelFetchError, fetch_snapshot
from shorts.channel.store import SnapshotRepository
from shorts.config import Settings
from shorts.publish.youtube import Readers, YouTubeError
from shorts.storage.db import connect
from shorts.storage.repositories import VideoRepository

log = logging.getLogger(__name__)

KEEP_DAYS = 120  # one snapshot a day is kept for this long


class ReadAccount(Protocol):
    def readers(self) -> Readers: ...


def _now() -> datetime:
    return datetime.now(UTC)


class ChannelWatcher:
    def __init__(self, settings: Settings, account: ReadAccount, *, fetch: Callable[..., object] = fetch_snapshot,
                 clock: Callable[[], datetime] = _now) -> None:
        self._settings = settings
        self._account = account
        self._fetch = fetch
        self._clock = clock

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self._settings.data_dir / "shorts.db")
        try:
            yield conn
        finally:
            conn.close()

    def refresh(self) -> str:
        """Read the channel now and keep the numbers. Returns a sentence for the owner."""
        try:
            readers = self._account.readers()
            with self._db() as conn:
                app_ids = VideoRepository(conn).youtube_ids()
            snapshot = self._fetch(readers.data, readers.analytics, app_ids=app_ids, now=self._clock(),
                                   analytics_note=readers.note)
        except (YouTubeError, ChannelFetchError) as exc:  # NotConnected is a YouTubeError
            log.warning("Channel numbers not updated: %s", exc)
            return f"Channel numbers not updated: {exc}"
        with self._db() as conn:
            repo = SnapshotRepository(conn)
            repo.save(snapshot)
            repo.prune(KEEP_DAYS, now=self._clock())
        log.info("Channel numbers updated: %d subscribers, %d videos", snapshot.subscribers, len(snapshot.videos))
        note = " (without YouTube Analytics: see the first tip)" if snapshot.analytics_note else ""
        return f"Channel numbers updated{note}."

    def is_stale(self, max_age: timedelta) -> bool:
        with self._db() as conn:
            latest = SnapshotRepository(conn).latest()
        return latest is None or self._clock() - latest.taken_at >= max_age

    def refresh_if_stale(self, max_age: timedelta) -> None:
        """For automatic mode: never lets a watcher problem stop a video run."""
        try:
            if self.is_stale(max_age):
                self.refresh()
        except Exception:
            log.exception("Channel watcher refresh failed")

    def report(self, tz: tzinfo | None = None) -> Report | None:
        with self._db() as conn:
            latest = SnapshotRepository(conn).latest()
        return build_report(latest, tz, now=self._clock()) if latest else None
