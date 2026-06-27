"""Phase D weekly universe persistence (separate from the MSCI `universes` table).

Stores a 2-column ticker list — Symbol (display) + FactSet ticker (used in
formulas) — as rows_json on the weekly_universe table. Mirrors the newest-active
rule used by settings_store.get_active_universe: the version flagged is_active
wins, else the newest upload. No web deps; idempotent table creation so the
store works standalone in tests.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..db import get_conn

_DDL = """
CREATE TABLE IF NOT EXISTS weekly_universe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    created_at TEXT,
    is_active INTEGER DEFAULT 0,
    rows_json TEXT NOT NULL
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


def save_universe(
    rows: List[Dict[str, str]],
    name: str = "",
    make_active: bool = True,
    db_path: Optional[str] = None,
) -> int:
    """Persist a weekly universe. ``rows`` is a list of
    {"symbol":..,"factset_ticker":..} dicts. Returns the new row id."""
    init(db_path)
    clean: List[Dict[str, str]] = []
    for r in rows or []:
        fs = str(r.get("factset_ticker") or "").strip()
        sym = str(r.get("symbol") or "").strip()
        if not fs:
            continue
        rec: Dict[str, str] = {"symbol": sym or fs, "factset_ticker": fs}
        # Optional per-row sector (used as a GICS fallback downstream).
        sec = str(r.get("sector") or "").strip()
        if sec and sec.lower() != "nan":
            rec["sector"] = sec
        clean.append(rec)
    conn = get_conn(db_path)
    try:
        if make_active:
            conn.execute("UPDATE weekly_universe SET is_active=0")
        cur = conn.execute(
            "INSERT INTO weekly_universe(name,created_at,is_active,rows_json) "
            "VALUES(?,?,?,?)",
            (name, _now(), int(make_active), json.dumps(clean)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_universes(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    init(db_path)
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT id,name,created_at,is_active FROM weekly_universe ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _hydrate(row) -> Dict[str, Any]:
    out = dict(row)
    try:
        out["rows"] = json.loads(out.get("rows_json") or "[]")
    except Exception:
        out["rows"] = []
    return out


def get_universe(uid: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    init(db_path)
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM weekly_universe WHERE id=?", (int(uid),)
        ).fetchone()
    finally:
        conn.close()
    return _hydrate(row) if row else None


def get_active(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Active = the version flagged is_active (explicit pin or newest upload,
    auto-activated on add). If none flagged but versions exist, the newest."""
    init(db_path)
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM weekly_universe WHERE is_active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM weekly_universe ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return _hydrate(row) if row else None
    finally:
        conn.close()


def set_active(uid: int, db_path: Optional[str] = None) -> None:
    init(db_path)
    conn = get_conn(db_path)
    try:
        conn.execute("UPDATE weekly_universe SET is_active=0")
        conn.execute("UPDATE weekly_universe SET is_active=1 WHERE id=?", (int(uid),))
        conn.commit()
    finally:
        conn.close()
