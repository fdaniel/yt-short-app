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
