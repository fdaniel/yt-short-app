from shorts.dashboard.app import Dashboard
from shorts.models import VideoStatus
from shorts.publish.youtube import YouTubeError
from shorts.storage.db import connect
from shorts.storage.repositories import VideoRepository

from tests.dashboard.conftest import FakeAccount


def _status(settings, vid):
    conn = connect(settings.data_dir / "shorts.db")
    try:
        return VideoRepository(conn).get(vid)
    finally:
        conn.close()


def _dash(settings, account=None, opened=None):
    return Dashboard(settings, account or FakeAccount(), opener=(opened.append if opened is not None else print))


def test_view_groups_videos_by_tab(settings, make_ready_video):
    review = make_ready_video("A")
    make_ready_video("B", VideoStatus.APPROVED)
    view = _dash(settings).view("review")
    assert [c.record.id for c in view.cards] == [review]
    assert view.counts["review"] == 1 and view.counts["published"] == 1
    card = view.cards[0]
    assert card.meta["title"] == "A" and card.has_file
    assert (card.score, card.explanation, card.source) == (0.81, "fresh, 2 sources", "NVIDIA Newsroom")
    assert view.made_today == 2 and view.daily_limit == settings.discovery.max_videos_per_day and view.channel.title == "Tech Bits"


def test_view_survives_broken_metadata(settings, make_ready_video):
    vid = make_ready_video()
    (settings.data_dir / "exports" / str(vid) / "metadata.json").write_text("{not json")
    assert _dash(settings).view("review").cards[0].meta == {}


def test_view_shows_recent_run_log_lines(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "run.log").write_text(
        "2026-10-18 17:02:10,027 INFO httpx: HTTP Request: POST https://x\n"
        "2026-10-18 17:10:15,068 INFO shorts.auto_cli: Run finished: 1 made, reason=None, 68 stories considered\n")
    lines = _dash(settings).view("review").run_lines
    assert lines == ("2026-10-18 17:10:15 Run finished: 1 made, reason=None, 68 stories considered",)


def test_upload_publishes_and_records_link(settings, make_ready_video):
    vid = make_ready_video()
    account = FakeAccount()
    message = _dash(settings, account).upload(vid)
    assert "Tech Bits" in message
    record = _status(settings, vid)
    assert record.status == VideoStatus.APPROVED and record.youtube_id == "abcdefghijk"
    path, body = account.uploads[0]
    assert path.name == "video.mp4" and body["snippet"]["title"] == "RTX 5090 announced"


def test_upload_kept_private_explains_audit(settings, make_ready_video):
    message = _dash(settings, FakeAccount(privacy="private")).upload(make_ready_video())
    assert "private" in message and "audit" in message


def test_upload_failure_leaves_video_for_review(settings, make_ready_video):
    vid = make_ready_video()
    message = _dash(settings, FakeAccount(error=YouTubeError("YouTube refused the upload: quota"))).upload(vid)
    assert "quota" in message
    assert _status(settings, vid).status == VideoStatus.AWAITING_APPROVAL


def test_upload_twice_is_refused(settings, make_ready_video):
    vid = make_ready_video()
    account = FakeAccount()
    _dash(settings, account).upload(vid)
    assert "already" in _dash(settings, account).upload(vid)
    assert len(account.uploads) == 1


def test_mark_uploaded_with_link(settings, make_ready_video):
    vid = make_ready_video()
    _dash(settings).mark_uploaded(vid, "https://youtube.com/shorts/dQw4w9WgXcQ")
    assert _status(settings, vid).youtube_id == "dQw4w9WgXcQ"


def test_mark_uploaded_bad_link_changes_nothing(settings, make_ready_video):
    vid = make_ready_video()
    assert "link" in _dash(settings).mark_uploaded(vid, "https://evil.example/x")
    assert _status(settings, vid).status == VideoStatus.AWAITING_APPROVAL


def test_discard_frees_the_video_file(settings, make_ready_video):
    vid = make_ready_video()
    _dash(settings).discard(vid)
    assert _status(settings, vid).status == VideoStatus.DISCARDED
    export = settings.data_dir / "exports" / str(vid)
    assert not (export / "video.mp4").exists() and (export / "metadata.json").exists()


def test_unknown_video_is_a_message(settings):
    assert "No video #99" in _dash(settings).discard(99)


def test_open_folder_hands_path_to_opener(settings, make_ready_video):
    vid = make_ready_video()
    opened = []
    _dash(settings, opened=opened).open_folder(vid)
    assert opened == [settings.data_dir / "exports" / str(vid)]


def test_video_file_only_inside_data_dir(settings, make_ready_video, tmp_path):
    vid = make_ready_video()
    dash = _dash(settings)
    assert dash.video_file(vid).name == "video.mp4"
    conn = connect(settings.data_dir / "shorts.db")
    conn.execute("UPDATE videos SET output_path = ? WHERE id = ?", (str(tmp_path / "secret.txt"), vid))
    conn.commit()
    conn.close()
    (tmp_path / "secret.txt").write_text("x")
    assert dash.video_file(vid) is None


def test_failed_save_after_upload_says_it_is_live_and_blocks_reupload(settings, make_ready_video, monkeypatch):
    import sqlite3

    vid = make_ready_video()
    account = FakeAccount()

    def locked(self, video_id, youtube_id):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(VideoRepository, "mark_published", locked)
    message = _dash(settings, account).upload(vid)
    assert "abcdefghijk" in message and "IS on YouTube" in message
    assert _status(settings, vid).status == VideoStatus.UPLOADING
    monkeypatch.undo()
    assert "already" in _dash(settings, account).upload(vid)
    assert len(account.uploads) == 1


def test_refused_upload_goes_back_to_review(settings, make_ready_video):
    vid = make_ready_video()
    _dash(settings, FakeAccount(error=YouTubeError("YouTube refused the upload: quota"))).upload(vid)
    assert _status(settings, vid).status == VideoStatus.AWAITING_APPROVAL


def test_private_upload_is_not_filed_as_published(settings, make_ready_video):
    vid = make_ready_video()
    message = _dash(settings, FakeAccount(privacy="private")).upload(vid)
    assert "private" in message and "by hand" in message
    assert _status(settings, vid).status == VideoStatus.AWAITING_APPROVAL


def test_back_to_review_releases_a_stuck_upload(settings, make_ready_video):
    vid = make_ready_video()
    conn = connect(settings.data_dir / "shorts.db")
    VideoRepository(conn).claim_upload(vid)
    conn.close()
    dash = _dash(settings)
    assert [c.record.id for c in dash.view("review").cards] == [vid]
    dash.back_to_review(vid)
    assert _status(settings, vid).status == VideoStatus.AWAITING_APPROVAL


def test_already_published_wording(settings, make_ready_video):
    vid = make_ready_video(status=VideoStatus.APPROVED)
    assert "already published" in _dash(settings).upload(vid)


def test_discard_reports_undeletable_file(settings, make_ready_video, monkeypatch):
    from pathlib import Path

    vid = make_ready_video()

    def denied(self, missing_ok=False):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", denied)
    message = _dash(settings).discard(vid)
    assert "discarded" in message and "could not be deleted" in message
