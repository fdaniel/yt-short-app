from datetime import timedelta

from shorts.channel.store import SnapshotRepository

from tests.channel.helpers import NOW, snapshot, video


def test_the_latest_snapshot_is_returned(conn):
    repo = SnapshotRepository(conn)
    assert repo.latest() is None
    repo.save(snapshot(video(1, views=100), taken_at=NOW - timedelta(hours=7)))
    repo.save(snapshot(video(1, views=150)))
    assert repo.latest().videos[0].views == 150


def test_old_snapshots_are_pruned_but_one_a_day_is_kept(conn):
    repo = SnapshotRepository(conn)
    for hours in range(0, 72, 6):
        repo.save(snapshot(video(1), taken_at=NOW - timedelta(hours=hours)))
    repo.prune(keep_days=60, now=NOW)
    assert len(repo.history(days=30, now=NOW)) == 4  # the last one of each day: 7, 8, 9 and 10 November


def test_a_damaged_row_is_skipped(conn):
    repo = SnapshotRepository(conn)
    repo.save(snapshot(video(1)))
    conn.execute("INSERT INTO channel_snapshots (taken_at, data) VALUES (?, ?)", ("2026-11-10T13:00:00+00:00", "{"))
    conn.commit()
    assert repo.latest() is not None
