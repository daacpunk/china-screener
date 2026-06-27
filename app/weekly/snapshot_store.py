"""Phase D weekly snapshot persistence (separate from the MSCI `snapshots` table).

A weekly snapshot is the ingested, dated dataset: per-ticker date/close/volume
series plus the HSI date/close series, stored as data_json. Newest-active rule,
idempotent table creation. No web deps.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..db import get_conn

_DDL = """
CREATE TABLE IF NOT EXISTS weekly_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    created_at TEXT,
    is_active INTEGER DEFAULT 0,
    data_json TEXT NOT NULL
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


def save_snapshot(
    data: Dict[str, Any],
    name: str = "",
    make_active: bool = True,
    db_path: Optional[str] = None,
) -> int:
    """Persist a weekly snapshot dict (tidy per-ticker + HSI + meta). Returns id."""
    init(db_path)
    conn = get_conn(db_path)
    try:
        if make_active:
            conn.execute("UPDATE weekly_snapshots SET is_active=0")
        cur = conn.execute(
            "INSERT INTO weekly_snapshots(name,created_at,is_active,data_json) "
            "VALUES(?,?,?,?)",
            (name, _now(), int(make_active), json.dumps(data)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_snapshots(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    init(db_path)
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT id,name,created_at,is_active FROM weekly_snapshots ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _hydrate(row) -> Dict[str, Any]:
    out = dict(row)
    try:
        out["data"] = json.loads(out.get("data_json") or "{}")
    except Exception:
        out["data"] = {}
    return out


def get_snapshot(sid: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    init(db_path)
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM weekly_snapshots WHERE id=?", (int(sid),)
        ).fetchone()
    finally:
        conn.close()
    return _hydrate(row) if row else None


def get_active(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    init(db_path)
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM weekly_snapshots WHERE is_active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM weekly_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return _hydrate(row) if row else None
    finally:
        conn.close()


def set_active(sid: int, db_path: Optional[str] = None) -> None:
    init(db_path)
    conn = get_conn(db_path)
    try:
        conn.execute("UPDATE weekly_snapshots SET is_active=0")
        conn.execute("UPDATE weekly_snapshots SET is_active=1 WHERE id=?", (int(sid),))
        conn.commit()
    finally:
        conn.close()


def delete_snapshot(sid: int, db_path: Optional[str] = None) -> bool:
    """Delete one snapshot row by id. Returns True if a row was removed.

    Idempotent and crash-proof: a missing id (or any error) yields False, never
    raises. If the deleted row was the active one no special handling is needed —
    ``get_active`` already falls back to the newest remaining row.
    """
    try:
        init(db_path)
        conn = get_conn(db_path)
        try:
            cur = conn.execute(
                "DELETE FROM weekly_snapshots WHERE id=?", (int(sid),)
            )
            conn.commit()
            return bool(cur.rowcount)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — never raise
        return False


def clear_all_snapshots(db_path: Optional[str] = None) -> int:
    """Delete ALL rows in weekly_snapshots; return the count removed.

    Frees the (potentially large) data_json blobs. Idempotent and crash-proof:
    on an empty table returns 0, on any error returns 0, never raises.
    """
    try:
        init(db_path)
        conn = get_conn(db_path)
        try:
            cur = conn.execute("DELETE FROM weekly_snapshots")
            conn.commit()
            return int(cur.rowcount or 0)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — never raise
        return 0
