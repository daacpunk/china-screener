"""SQLite connection + schema init.

DB_PATH env (default /data/app.db for Railway volume; falls back to ./app.db
if /data is not writable). All persistence (universes, dictionaries, snapshots,
settings, encrypted API keys) lives here and survives restarts.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

_DEFAULT = "/data/app.db"
_FALLBACK = "./app.db"


def resolve_db_path() -> str:
    path = os.environ.get("DB_PATH", _DEFAULT)
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # test writability
        test = p.parent / ".write_test"
        test.write_text("ok")
        test.unlink(missing_ok=True)
        return str(p)
    except Exception:
        fb = Path(_FALLBACK)
        fb.parent.mkdir(parents=True, exist_ok=True)
        return str(fb)


def get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or resolve_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    provider TEXT PRIMARY KEY,        -- perplexity | anthropic | deepseek
    enc_value TEXT,                   -- Fernet-encrypted key
    model TEXT,
    enabled INTEGER DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS dictionaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    note TEXT,
    json_text TEXT NOT NULL,
    md_text TEXT,
    created_at TEXT,
    is_active INTEGER DEFAULT 0,
    is_demo INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS universes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    note TEXT,
    csv_text TEXT NOT NULL,           -- tidy universe rows as CSV
    manual_csv TEXT,                  -- manual added tickers as CSV
    created_at TEXT,
    is_active INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    note TEXT,
    csv_text TEXT NOT NULL,           -- tidy price/volume CSV: ticker,date,close,volume
    quality_json TEXT,
    created_at TEXT,
    is_active INTEGER DEFAULT 0
);
"""


def init_db(db_path: Optional[str] = None) -> None:
    conn = get_conn(db_path)
    try:
        conn.executescript(SCHEMA)
        # Safe migration for pre-existing DBs created before is_demo existed.
        try:
            conn.execute("ALTER TABLE dictionaries ADD COLUMN is_demo INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()
    finally:
        conn.close()
