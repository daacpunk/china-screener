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


def _ensure_audience_column(conn) -> None:
    """Idempotently add the optional ``audience`` column to an existing table so
    pre-change rows keep working (they read back as NULL -> treated as
    'institutional'). Never raises on a DB that already has it."""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(weekly_notes)").fetchall()}
        if "audience" not in cols:
            conn.execute("ALTER TABLE weekly_notes ADD COLUMN audience TEXT")
            conn.commit()
    except Exception:  # noqa: BLE001 — migration is best-effort
        pass


def init(db_path: Optional[str] = None) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute(_DDL)
        conn.commit()
        _ensure_audience_column(conn)
    finally:
        conn.close()


def save_note(
    asof: Any,
    provider: Optional[str],
    metrics: Any,
    markdown: str,
    db_path: Optional[str] = None,
    audience: str = "institutional",
) -> int:
    """Persist one weekly note. ``audience`` ("institutional"|"retail") is stored
    in its own column AND mirrored into ``metrics['_audience']`` so it round-trips
    even for callers/readers that only look at the metrics blob. Backward
    compatible: existing callers that omit ``audience`` default to institutional.
    """
    init(db_path)
    aud = "retail" if str(audience) == "retail" else "institutional"
    # Mirror into the metrics blob (defensive: also readable without the column).
    if isinstance(metrics, dict):
        metrics = {**metrics, "_audience": aud}
    conn = get_conn(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO weekly_notes"
            "(created_at,asof,provider,metrics_json,markdown,audience) "
            "VALUES(?,?,?,?,?,?)",
            (
                _now(),
                str(asof) if asof is not None else None,
                provider or "",
                json.dumps(metrics) if metrics is not None else None,
                markdown or "",
                aud,
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
            "SELECT id,created_at,asof,provider,audience FROM weekly_notes "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["audience"] = d.get("audience") or "institutional"
            out.append(d)
        return out
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
    # Resolve audience: explicit column wins, else the mirror in metrics, else
    # institutional (covers pre-migration rows).
    aud = out.get("audience") or (out["metrics"] or {}).get("_audience")
    out["audience"] = "retail" if aud == "retail" else "institutional"
    return out
