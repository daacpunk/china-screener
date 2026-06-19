"""Persistence for Research Notes over the same SQLite db settings_store uses.

The ``research_notes`` table is part of db.SCHEMA (created at startup), but we
also create it idempotently on import so the store works standalone (e.g. tests
that touch notes before any other init). No web deps.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .db import get_conn

_DDL = """
CREATE TABLE IF NOT EXISTS research_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    asof TEXT,
    provider TEXT,
    candidates_json TEXT,
    markdown TEXT,
    council_json TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init(db_path: Optional[str] = None) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute(_DDL)
        conn.commit()
    finally:
        conn.close()


def save_note(
    asof: Any,
    provider: Optional[str],
    candidates: Any,
    markdown: str,
    council: Any = None,
    db_path: Optional[str] = None,
) -> int:
    init(db_path)
    conn = get_conn(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO research_notes(created_at,asof,provider,candidates_json,markdown,council_json) "
            "VALUES(?,?,?,?,?,?)",
            (
                _now(),
                str(asof) if asof is not None else None,
                provider or "",
                json.dumps(candidates) if candidates is not None else None,
                markdown or "",
                json.dumps(council) if council is not None else None,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_notes(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    init(db_path)
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT id,created_at,asof,provider FROM research_notes "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_note(note_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    init(db_path)
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM research_notes WHERE id=?", (int(note_id),)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    out = dict(row)
    out["candidates"] = json.loads(out["candidates_json"]) if out.get("candidates_json") else []
    out["council"] = json.loads(out["council_json"]) if out.get("council_json") else None
    return out
