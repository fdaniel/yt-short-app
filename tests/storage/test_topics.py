from datetime import UTC, date, datetime, timedelta

from shorts.models import TopicStatus, VideoFormat, VideoStatus
from shorts.storage import db
from shorts.storage.repositories import VideoRepository
from shorts.storage.topics import TopicRepository

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _record(repo, url, status=TopicStatus.SKIPPED, title="DLSS 5 announced", score=None):
    return repo.record(url, "NVIDIA Blog", title, NOW - timedelta(hours=2), status, score, "why")


def test_record_and_seen(conn):
    repo = TopicRepository(conn)
    _record(repo, "https://a/1")
    _record(repo, "https://a/2")
    assert repo.seen_urls() == {"https://a/1", "https://a/2"}


def test_rerecord_updates_instead_of_duplicating(conn):
    repo = TopicRepository(conn)
    first = _record(repo, "https://a/1")
    again = _record(repo, "https://a/1", TopicStatus.PICKED, score=0.8)
    assert first == again
    row = conn.execute("SELECT status, score, COUNT(*) AS n FROM topics").fetchone()
    assert (row["status"], row["score"], row["n"]) == ("picked", 0.8, 1)


def test_link_video(conn):
    repo = TopicRepository(conn)
    topic = _record(repo, "https://a/1", TopicStatus.PICKED)
    video = VideoRepository(conn).create("https://a/1", None, VideoFormat.NEWS_FLASH)
    repo.link_video(topic, video, TopicStatus.MADE)
    row = conn.execute("SELECT status, video_id FROM topics").fetchone()
    assert (row["status"], row["video_id"]) == ("made", video)


def test_recent_titles(conn):
    repo = TopicRepository(conn)
    _record(repo, "https://a/1", TopicStatus.MADE, title="RTX Spark laptops")
    _record(repo, "https://a/2", TopicStatus.SKIPPED, title="AMD board news")
    _record(repo, "https://a/3", TopicStatus.PICKED, title="Old story")
    conn.execute("UPDATE topics SET created_at = ? WHERE url = 'https://a/3'", ((NOW - timedelta(days=20)).isoformat(),))
    videos = VideoRepository(conn)
    vid = videos.create("https://x", None, VideoFormat.NEWS_FLASH)
    videos.save_script(vid, "{}", "Hand-made video title")
    titles = repo.recent_titles(14, NOW + timedelta(seconds=1))
    assert set(titles) == {"RTX Spark laptops", "Hand-made video title"}


def test_videos_made_on_ignores_failed_and_other_days(conn):
    videos = VideoRepository(conn)
    ok = videos.create("https://x/1", None, VideoFormat.NEWS_FLASH)
    bad = videos.create("https://x/2", None, VideoFormat.NEWS_FLASH)
    old = videos.create("https://x/3", None, VideoFormat.NEWS_FLASH)
    videos.set_status(bad, VideoStatus.FAILED, "boom")
    conn.execute("UPDATE videos SET created_at = ? WHERE id = ?", ((datetime.now(UTC) - timedelta(days=3)).isoformat(), old))
    today = datetime.now(UTC).astimezone().date()
    repo = TopicRepository(conn)
    assert repo.videos_made_on(today) == 1
    assert repo.videos_made_on(date(2000, 1, 1)) == 0
    assert ok


def test_step1_database_upgrades_and_keeps_videos(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with monkeypatch.context() as m:
        m.setattr(db, "MIGRATIONS", db.MIGRATIONS[:1])
        old = db.connect(path)
        VideoRepository(old).create("https://kept", None, VideoFormat.NEWS_FLASH)
        old.close()
    conn = db.connect(path)
    assert VideoRepository(conn).get(1).news_url == "https://kept"
    assert TopicRepository(conn).seen_urls() == set()
