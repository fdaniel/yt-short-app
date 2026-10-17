"""Data access for videos, assets and the publisher blocklist."""

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from shorts.models import Asset, AssetKind, RightsBasis, VideoFormat, VideoStatus

ALLOWED: dict[VideoStatus, set[VideoStatus]] = {
    VideoStatus.SCRIPTING: {VideoStatus.FACT_CHECKED, VideoStatus.FAILED},
    VideoStatus.FACT_CHECKED: {VideoStatus.RENDERING, VideoStatus.FAILED},
    VideoStatus.RENDERING: {VideoStatus.AWAITING_APPROVAL, VideoStatus.FAILED},
    VideoStatus.AWAITING_APPROVAL: {
        VideoStatus.APPROVED,
        VideoStatus.DISCARDED,
        VideoStatus.EXPIRED,
    },
}


class InvalidTransition(Exception):
    """A video status change that the state machine does not allow."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _path_or_none(value: str | None) -> Path | None:
    return Path(value) if value else None


@dataclass(frozen=True)
class VideoRecord:
    id: int
    news_url: str
    steam_app_id: int | None
    format: VideoFormat
    status: VideoStatus
    failure_reason: str | None
    title: str | None
    script_json: str | None
    output_path: Path | None
    metadata_path: Path | None
    content_hash: str | None
    created_at: str
    updated_at: str


class VideoRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, news_url: str, steam_app_id: int | None, fmt: VideoFormat) -> int:
        now = _now()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO videos (news_url, steam_app_id, format, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (news_url, steam_app_id, fmt.value, VideoStatus.SCRIPTING.value, now, now),
            )
        return int(cur.lastrowid)

    def get(self, video_id: int) -> VideoRecord:
        row = self._conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        if row is None:
            raise KeyError(f"video {video_id} not found")
        return VideoRecord(
            id=row["id"],
            news_url=row["news_url"],
            steam_app_id=row["steam_app_id"],
            format=VideoFormat(row["format"]),
            status=VideoStatus(row["status"]),
            failure_reason=row["failure_reason"],
            title=row["title"],
            script_json=row["script_json"],
            output_path=_path_or_none(row["output_path"]),
            metadata_path=_path_or_none(row["metadata_path"]),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def set_status(
        self, video_id: int, status: VideoStatus, failure_reason: str | None = None
    ) -> None:
        current = self.get(video_id).status
        if status not in ALLOWED.get(current, set()):
            raise InvalidTransition(f"video {video_id}: {current} -> {status} is not allowed")
        self._update(video_id, status=status.value, failure_reason=failure_reason)

    def save_script(self, video_id: int, script_json: str, title: str) -> None:
        self._update(video_id, script_json=script_json, title=title)

    def save_output(
        self, video_id: int, output_path: Path, metadata_path: Path, content_hash: str
    ) -> None:
        self._update(
            video_id,
            output_path=str(output_path),
            metadata_path=str(metadata_path),
            content_hash=content_hash,
        )

    def _update(self, video_id: int, **fields: object) -> None:
        # Column names come only from this module's call sites, never from user input.
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._conn:
            self._conn.execute(
                f"UPDATE videos SET {assignments}, updated_at = ? WHERE id = ?",
                (*fields.values(), _now(), video_id),
            )


class AssetRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, asset: Asset, video_id: int) -> Asset:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO assets (video_id, kind, local_path, source_url, source_platform,"
                " rightsholder, rights_basis, licence_terms_ref, music_stripped, fetched_at, notes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    video_id,
                    asset.kind.value,
                    str(asset.local_path),
                    asset.source_url,
                    asset.source_platform,
                    asset.rightsholder,
                    asset.rights_basis.value,
                    asset.licence_terms_ref,
                    int(asset.music_stripped),
                    asset.fetched_at.isoformat(),
                    asset.notes,
                ),
            )
        return replace(asset, id=int(cur.lastrowid))

    def list_for_video(self, video_id: int) -> list[Asset]:
        rows = self._conn.execute(
            "SELECT * FROM assets WHERE video_id = ? ORDER BY id", (video_id,)
        ).fetchall()
        return [
            Asset(
                id=row["id"],
                kind=AssetKind(row["kind"]),
                local_path=Path(row["local_path"]),
                source_url=row["source_url"],
                source_platform=row["source_platform"],
                rightsholder=row["rightsholder"],
                rights_basis=RightsBasis(row["rights_basis"]),
                licence_terms_ref=row["licence_terms_ref"],
                music_stripped=bool(row["music_stripped"]),
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                notes=row["notes"],
            )
            for row in rows
        ]


class BlocklistRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, name: str, reason: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO blocked_publishers (name, reason, blocked_at)"
                " VALUES (?, ?, ?)",
                (name.strip().lower(), reason, _now()),
            )

    def names(self) -> set[str]:
        rows = self._conn.execute("SELECT name FROM blocked_publishers").fetchall()
        return {row["name"] for row in rows}
