"""What the dashboard shows and the buttons it offers, independent of HTTP."""

import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from shorts.config import Settings
from shorts.dashboard.links import youtube_id_from
from shorts.models import VideoStatus
from shorts.publish.youtube import Channel, UploadResult, YouTubeError, upload_body
from shorts.storage.db import connect
from shorts.storage.repositories import InvalidTransition, VideoRecord, VideoRepository
from shorts.storage.topics import TopicRepository

log = logging.getLogger(__name__)

TABS: dict[str, tuple[VideoStatus, ...]] = {
    "review": (VideoStatus.AWAITING_APPROVAL, VideoStatus.UPLOADING),
    "published": (VideoStatus.APPROVED,),
    "making": (VideoStatus.SCRIPTING, VideoStatus.FACT_CHECKED, VideoStatus.RENDERING),
    "discarded": (VideoStatus.DISCARDED, VideoStatus.EXPIRED),
    "failed": (VideoStatus.FAILED,),
}
MAX_VIDEOS = 300
RUN_LOG_TAIL_BYTES = 64 * 1024
RUN_LOG_LINES = 8
_RUN_LOGGERS = (" shorts.auto_cli: ", " shorts.discovery.runner: ")
# YouTube needs time to process the upload first; scheduling further out than this is almost surely a typo
SCHEDULE_MIN_AHEAD = timedelta(minutes=15)
SCHEDULE_MAX_AHEAD = timedelta(days=60)


def _already(video_id: int, status: VideoStatus) -> str:
    states = {
        VideoStatus.APPROVED: "already published",
        VideoStatus.UPLOADING: "already being uploaded (if that was interrupted, check YouTube Studio)",
        VideoStatus.DISCARDED: "discarded",
    }
    return f"Video #{video_id} is {states.get(status, status.value.replace('_', ' '))}."


class Account(Protocol):
    def channel(self) -> Channel | None: ...
    def upload(self, video_path: Path, body: dict[str, Any]) -> UploadResult: ...


@dataclass(frozen=True)
class VideoCard:
    record: VideoRecord
    meta: dict[str, Any]
    has_file: bool
    source: str | None = None
    score: float | None = None
    explanation: str = ""


@dataclass(frozen=True)
class DashboardView:
    tab: str
    cards: tuple[VideoCard, ...]
    counts: dict[str, int]
    made_today: int
    daily_limit: int
    channel: Channel | None
    run_lines: tuple[str, ...]
    privacy: str = "public"
    can_schedule: bool = False


def _load_meta(path: Path | None) -> dict[str, Any]:
    """metadata.json as written by the pipeline; {} when missing or damaged."""
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_lines(log_path: Path) -> tuple[str, ...]:
    """The last few lines automatic mode wrote about its runs, without the HTTP noise."""
    try:
        with log_path.open("rb") as fh:
            fh.seek(max(0, log_path.stat().st_size - RUN_LOG_TAIL_BYTES))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ()
    lines = []
    for line in text.splitlines():
        for marker in _RUN_LOGGERS:
            if marker in line:
                stamp, _, message = line.partition(marker)
                lines.append(f"{stamp[:19]} {message}")
    return tuple(lines[-RUN_LOG_LINES:])


class Dashboard:
    def __init__(self, settings: Settings, account: Account, opener: Callable[[Path], object]) -> None:
        self._settings = settings
        self._account = account
        self._opener = opener
        self._publish_lock = threading.Lock()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self._settings.data_dir / "shorts.db")
        try:
            yield conn
        finally:
            conn.close()

    def view(self, tab: str) -> DashboardView:
        tab = tab if tab in TABS else "review"
        with self._db() as conn:
            records = VideoRepository(conn).list_recent(MAX_VIDEOS)
            topics = TopicRepository(conn)
            cards = tuple(self._card(r, topics) for r in records if r.status in TABS[tab])
            made_today = topics.videos_made_on(date.today())
        return DashboardView(
            tab=tab,
            cards=cards,
            counts={name: sum(r.status in statuses for r in records) for name, statuses in TABS.items()},
            made_today=made_today,
            daily_limit=self._settings.discovery.max_videos_per_day,
            channel=self._account.channel(),
            run_lines=_run_lines(self._settings.data_dir / "run.log"),
            privacy=self._settings.youtube.privacy_status,
            can_schedule=self._settings.youtube.audit_approved,
        )

    def _card(self, record: VideoRecord, topics: TopicRepository) -> VideoCard:
        topic = topics.for_video(record.id)
        return VideoCard(
            record=record,
            meta=_load_meta(record.metadata_path),
            has_file=self._inside_data_dir(record.output_path) is not None,
            source=topic["source"] if topic else None,
            score=topic["score"] if topic else None,
            explanation=topic["explanation"] if topic else "",
        )

    def _inside_data_dir(self, path: Path | None) -> Path | None:
        """Only files the pipeline exported are ever served or deleted."""
        if path is None or not path.is_file():
            return None
        resolved = path.resolve()
        return resolved if resolved.is_relative_to((self._settings.data_dir / "exports").resolve()) else None

    def video_file(self, video_id: int) -> Path | None:
        with self._db() as conn:
            try:
                return self._inside_data_dir(VideoRepository(conn).get(video_id).output_path)
            except KeyError:
                return None

    def upload(self, video_id: int) -> str:
        """Upload through the YouTube API, public now."""
        return self._upload(video_id, None)

    def schedule(self, video_id: int, when: str) -> str:
        """Upload now through the YouTube API; YouTube makes it public at `when` (the page's local date and time)."""
        if not self._settings.youtube.audit_approved:
            return (f"Video #{video_id} was not scheduled: scheduling here works once Google approves your app (the"
                    " audit in the README). Until then, upload it by hand and pick Schedule in YouTube Studio.")
        try:
            publish_at = datetime.fromisoformat(when).astimezone()
        except ValueError:
            return f"Video #{video_id} was not scheduled: pick a date and time first."
        ahead = publish_at - datetime.now().astimezone()
        if ahead < SCHEDULE_MIN_AHEAD:
            return (f"Video #{video_id} was not scheduled: pick a time at least"
                    f" {SCHEDULE_MIN_AHEAD.seconds // 60} minutes from now.")
        if ahead > SCHEDULE_MAX_AHEAD:
            return f"Video #{video_id} was not scheduled: pick a time at most {SCHEDULE_MAX_AHEAD.days} days ahead."
        return self._upload(video_id, publish_at)

    def _upload(self, video_id: int, publish_at: datetime | None) -> str:
        """The row is claimed first, so no click, process or crash uploads twice."""
        with self._publish_lock, self._db() as conn:
            repo = VideoRepository(conn)
            try:
                record = repo.get(video_id)
            except KeyError:
                return f"No video #{video_id}."
            video = self._inside_data_dir(record.output_path)
            meta = _load_meta(record.metadata_path)
            if record.status == VideoStatus.AWAITING_APPROVAL and (video is None or not meta.get("title")):
                return f"Video #{video_id} has no video file or metadata to upload."
            if not repo.claim_upload(video_id):
                return _already(video_id, record.status)
            try:
                result = self._account.upload(video, upload_body(meta, self._settings.youtube, publish_at))
            except YouTubeError as exc:
                log.warning("Upload of video #%d failed: %s", video_id, exc)
                repo.set_status(video_id, VideoStatus.AWAITING_APPROVAL)
                return f"Video #{video_id} was not uploaded: {exc}"
            link = f"https://youtube.com/shorts/{result.video_id}"
            wanted = "private" if publish_at else self._settings.youtube.privacy_status
            if result.privacy_status and result.privacy_status != wanted:
                repo.set_status(video_id, VideoStatus.AWAITING_APPROVAL)
                return (f"YouTube made video #{video_id} {result.privacy_status}, not {wanted} ({link}): until Google"
                        " approves your app (the audit in the README) API uploads stay private. It is back in"
                        " To review: upload it by hand to publish it.")
            try:
                repo.mark_published(video_id, result.video_id)
            except sqlite3.Error as exc:
                log.exception("Video #%d is live as %s but could not be recorded", video_id, result.video_id)
                return (f"Video #{video_id} IS on YouTube ({link}) but the dashboard could not record it ({exc})."
                        " Do not upload it again: paste that link below and press Mark as published.")
        log.info("Uploaded video #%d as YouTube %s (%s, publish at %s)", video_id, result.video_id,
                 result.privacy_status, publish_at)
        channel = self._account.channel()
        to = f" to {channel.title}" if channel else ""
        if publish_at:
            return (f"Video #{video_id} uploaded{to} and scheduled for {publish_at:%d %b %H:%M}: {link}. YouTube Studio"
                    " should list it as Scheduled.")
        return f"Video #{video_id} uploaded{to}: {link}"

    def back_to_review(self, video_id: int) -> str:
        """After an interrupted upload the owner checked YouTube Studio and the video is not there."""
        _, message = self._transition(video_id, lambda repo: repo.set_status(video_id, VideoStatus.AWAITING_APPROVAL),
                                      f"Video #{video_id} is back in To review.")
        return message

    def mark_uploaded(self, video_id: int, link: str) -> str:
        """For videos uploaded by hand in YouTube Studio."""
        try:
            youtube_id = youtube_id_from(link)
        except ValueError as exc:
            return f"That YouTube link did not look right ({exc}); nothing changed."
        _, message = self._transition(video_id, lambda repo: repo.mark_published(video_id, youtube_id),
                                      f"Video #{video_id} marked as published.")
        return message

    def discard(self, video_id: int) -> str:
        """Discard and delete the video file (keeping its metadata) to free disk space."""
        video = self.video_file(video_id)
        changed, message = self._transition(
            video_id, lambda repo: repo.set_status(video_id, VideoStatus.DISCARDED), f"Video #{video_id} discarded."
        )
        if changed and video is not None:
            try:
                video.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("Could not delete %s: %s", video, exc)
                return f"Video #{video_id} discarded, but its file could not be deleted ({exc}): {video}"
        return message

    def _transition(self, video_id: int, change: Callable[[VideoRepository], None], done: str) -> tuple[bool, str]:
        with self._publish_lock, self._db() as conn:
            try:
                change(VideoRepository(conn))
            except KeyError:
                return False, f"No video #{video_id}."
            except InvalidTransition:
                return False, f"Video #{video_id} is already published or discarded."
        log.info(done)
        return True, done

    def open_folder(self, video_id: int) -> str:
        video = self.video_file(video_id)
        if video is None:
            return f"Video #{video_id} has no file to show."
        self._opener(video.parent)
        return f"Opened the folder of video #{video_id}: drag video.mp4 into YouTube's upload window."
