"""Phase D weekly-note persistence (separate from `research_notes`).

Mirrors notes_store: dated history of generated weekly one-pagers with their
computed metrics (metrics_json) and assembled markdown. Idempotent DDL.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..db import get_conn

_DDL = """
CREATE TABLE IF NOT EXISTS weekly_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    asof TEXT,
    provider TEXT,
    metrics_json TEXT,
    markdown TEXT
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
    metrics: Any,
    markdown: str,
    db_path: Optional[str] = None,
) -> int:
    init(db_path)
    conn = get_conn(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO weekly_notes(created_at,asof,provider,metrics_json,markdown) "
            "VALUES(?,?,?,?,?)",
            (
                _now(),
                str(asof) if asof is not None else None,
                provider or "",
                json.dumps(metrics) if metrics is not None else None,
                markdown or "",
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
            "SELECT id,created_at,asof,provider FROM weekly_notes "
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
            "SELECT * FROM weekly_notes WHERE id=?", (int(note_id),)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    out = dict(row)
    out["metrics"] = json.loads(out["metrics_json"]) if out.get("metrics_json") else {}
    return out
