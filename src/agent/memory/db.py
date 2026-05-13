"""SQLite connection + schema migrations.

One file, three responsibilities:
  * Episodic: append-only tool-call audit log.
  * Tasks:    persistent todo queue (cron-like or one-shot).
  * Notes:    free-form notes, full-text searchable via FTS5.

Working memory (recent chat turns) lives in-process in a ring buffer -
it's fine to lose on restart.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import get_settings

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS episodic (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL DEFAULT (datetime('now')),
    chat_id     INTEGER,
    skill       TEXT    NOT NULL,
    input_json  TEXT    NOT NULL,
    result_json TEXT,
    status      TEXT    NOT NULL CHECK (status IN ('ok','error','simulated','denied')),
    tx_hash     TEXT,
    chain       TEXT,
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_episodic_ts    ON episodic(ts);
CREATE INDEX IF NOT EXISTS idx_episodic_skill ON episodic(skill);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ts   TEXT    NOT NULL DEFAULT (datetime('now')),
    title        TEXT    NOT NULL,
    description  TEXT,
    schedule     TEXT,                     -- cron expr or ISO datetime or NULL
    status       TEXT    NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','running','done','failed','cancelled')),
    last_run_ts  TEXT,
    last_result  TEXT,
    run_count    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL DEFAULT (datetime('now')),
    tag        TEXT,
    body       TEXT    NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
    USING fts5(body, tag, content='notes', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, body, tag) VALUES (new.id, new.body, new.tag);
END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, body, tag)
        VALUES('delete', old.id, old.body, old.tag);
END;
CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, body, tag)
        VALUES('delete', old.id, old.body, old.tag);
    INSERT INTO notes_fts(rowid, body, tag) VALUES (new.id, new.body, new.tag);
END;

-- Daily counters used by policy (e.g., max_new_wallets_per_day).
CREATE TABLE IF NOT EXISTS counters (
    key  TEXT NOT NULL,
    day  TEXT NOT NULL,   -- YYYY-MM-DD
    n    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (key, day)
);
"""


def _db_path() -> Path:
    p = get_settings().data_dir / "agent.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_db() -> sqlite3.Connection:
    """Open a new SQLite connection with sensible defaults.

    Callers are responsible for closing. Short-lived per-operation connections
    are fine under WAL and keep threading simple.
    """
    conn = sqlite3.connect(_db_path(), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_db()
    try:
        conn.executescript(_SCHEMA)
    finally:
        conn.close()
