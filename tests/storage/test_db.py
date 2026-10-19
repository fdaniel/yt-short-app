import sqlite3

import pytest

from shorts.storage import db


def test_failed_migration_leaves_no_partial_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS + ("CREATE TABLE half (x); THIS IS NOT SQL;",))
    with pytest.raises(sqlite3.Error):
        db.connect(tmp_path / "s.db")
    conn = sqlite3.connect(tmp_path / "s.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "half" not in tables
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == len(db.MIGRATIONS) - 1


def test_migration_already_applied_by_another_process_is_skipped(tmp_path):
    from shorts.storage.db import MIGRATIONS, _migrate, connect

    conn = connect(tmp_path / "s.db")
    last = len(MIGRATIONS)
    _migrate(conn, last, MIGRATIONS[-1])  # a second process got there first: must be a no-op, not a crash
    assert conn.execute("select count(*) from schema_version where version = ?", (last,)).fetchone()[0] == 1
