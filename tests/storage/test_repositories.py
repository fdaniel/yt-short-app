from pathlib import Path

import pytest

from shorts.models import VideoFormat, VideoStatus
from shorts.storage.db import connect
from shorts.storage.repositories import (
    AssetRepository,
    BlocklistRepository,
    InvalidTransition,
    VideoRepository,
)


def test_connect_is_idempotent(tmp_path):
    db = tmp_path / "s.db"
    connect(db).close()
    conn = connect(db)
    assert conn.execute("select max(version) from schema_version").fetchone()[0] >= 1
    assert conn.execute("select count(*) from schema_version").fetchone()[0] == 1


def test_video_happy_path_transitions(conn):
    repo = VideoRepository(conn)
    vid = repo.create("https://nvidia.com/x", 1091500, VideoFormat.NEWS_FLASH)
    assert repo.get(vid).status == VideoStatus.SCRIPTING
    for s in ("fact_checked", "rendering", "awaiting_approval"):
        repo.set_status(vid, VideoStatus(s))
    record = repo.get(vid)
    assert record.status == VideoStatus.AWAITING_APPROVAL
    assert record.steam_app_id == 1091500 and record.format == VideoFormat.NEWS_FLASH


def test_cannot_skip_fact_check(conn):
    repo = VideoRepository(conn)
    vid = repo.create("https://a.com", None, VideoFormat.NEWS_FLASH)
    with pytest.raises(InvalidTransition):
        repo.set_status(vid, VideoStatus.RENDERING)


def test_terminal_state_cannot_change(conn):
    repo = VideoRepository(conn)
    vid = repo.create("https://a.com", None, VideoFormat.NEWS_FLASH)
    repo.set_status(vid, VideoStatus.FAILED, "boom")
    with pytest.raises(InvalidTransition):
        repo.set_status(vid, VideoStatus.FACT_CHECKED)


def test_failed_stores_reason(conn):
    repo = VideoRepository(conn)
    vid = repo.create("https://a.com", None, VideoFormat.NEWS_FLASH)
    repo.set_status(vid, VideoStatus.FAILED, "no source text")
    assert repo.get(vid).failure_reason == "no source text"


def test_unknown_video_raises_keyerror(conn):
    with pytest.raises(KeyError):
        VideoRepository(conn).get(999)


def test_save_script_and_output(conn):
    repo = VideoRepository(conn)
    vid = repo.create("https://a.com", None, VideoFormat.VERSUS)
    repo.save_script(vid, '{"hook": "x"}', "Title")
    repo.save_output(vid, Path("/out/v.mp4"), Path("/out/m.json"), "abc123")
    r = repo.get(vid)
    assert (r.title, r.script_json, r.content_hash) == ("Title", '{"hook": "x"}', "abc123")
    assert r.output_path == Path("/out/v.mp4") and r.metadata_path == Path("/out/m.json")


def test_asset_roundtrip(conn, make_asset):
    vid = VideoRepository(conn).create("https://a.com", None, VideoFormat.NEWS_FLASH)
    saved = AssetRepository(conn).add(make_asset(notes="n"), vid)
    assert saved.id is not None
    assert AssetRepository(conn).list_for_video(vid) == [saved]


def test_blocklist_case_insensitive(conn):
    BlocklistRepository(conn).add("CD PROJEKT RED", "claim on video 3")
    BlocklistRepository(conn).add("cd projekt red", "second claim")
    assert BlocklistRepository(conn).names() == {"cd projekt red"}
