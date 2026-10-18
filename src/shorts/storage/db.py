"""SQLite connection with ordered, idempotent migrations."""

import sqlite3
from pathlib import Path

MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_url TEXT NOT NULL,
        steam_app_id INTEGER,
        format TEXT NOT NULL,
        status TEXT NOT NULL,
        failure_reason TEXT,
        title TEXT,
        script_json TEXT,
        output_path TEXT,
        metadata_path TEXT,
        content_hash TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER NOT NULL REFERENCES videos(id),
        kind TEXT NOT NULL,
        local_path TEXT NOT NULL,
        source_url TEXT,
        source_platform TEXT NOT NULL,
        rightsholder TEXT NOT NULL,
        rights_basis TEXT NOT NULL,
        licence_terms_ref TEXT NOT NULL,
        music_stripped INTEGER NOT NULL,
        fetched_at TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE blocked_publishers (
        name TEXT PRIMARY KEY,
        reason TEXT NOT NULL,
        blocked_at TEXT NOT NULL
    );
    """,
)


def _migrate(conn: sqlite3.Connection, version: int, sql: str) -> None:
    """Apply one migration and record it in a single transaction: all of it or none of it."""
    try:
        conn.executescript(f"BEGIN;\n{sql}\n;INSERT INTO schema_version (version) VALUES ({int(version)});\nCOMMIT;")
    except sqlite3.Error:
        conn.rollback()
        raise


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database and apply pending migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    current = conn.execute("SELECT max(version) FROM schema_version").fetchone()[0] or 0
    for version, sql in enumerate(MIGRATIONS, start=1):
        if version > current:
            _migrate(conn, version, sql)
    return conn
