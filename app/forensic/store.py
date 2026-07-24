"""Phase E forensic-run persistence (separate from weekly_notes / research_notes).

Mirrors the weekly `note_store` pattern: a dated history of forensic runs with
their inputs (mode, company hints, source filenames), computed outputs
(composite score, letter rating, assembled markdown, metrics blob) and a status
flag. Idempotent DDL; a best-effort migration helper adds columns to older DBs
without ever raising. E0 stores the shell — scoring/extraction fill it later.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..db import get_conn

_DDL = """
CREATE TABLE IF NOT EXISTS forensic_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    mode TEXT,                 -- ipo | listed_pdf | listed_excel
    company_name TEXT,
    ticker TEXT,
    sector TEXT,
    listing_chapter TEXT,
    profile TEXT,              -- revenue_generating | pre_revenue | NULL
    composite_score REAL,
    letter_rating TEXT,
    markdown TEXT,
    metrics_json TEXT,
    source_filenames TEXT,
    status TEXT DEFAULT 'pending'   -- pending | ok | error
);
"""

# Columns that a fresh table must have; used by the best-effort migration so an
# older DB (should one ever exist) gains any missing column without raising.
_EXPECTED_COLUMNS = {
    "created_at": "TEXT",
    "mode": "TEXT",
    "company_name": "TEXT",
    "ticker": "TEXT",
    "sector": "TEXT",
    "listing_chapter": "TEXT",
    "profile": "TEXT",
    "composite_score": "REAL",
    "letter_rating": "TEXT",
    "markdown": "TEXT",
    "metrics_json": "TEXT",
    "source_filenames": "TEXT",
    "status": "TEXT",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_columns(conn) -> None:
    """Idempotently add any missing column to an existing forensic_runs table.
    Never raises — migration is best-effort so a partially-built DB still works."""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(forensic_runs)").fetchall()}
        for name, decl in _EXPECTED_COLUMNS.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE forensic_runs ADD COLUMN {name} {decl}")
        conn.commit()
    except Exception:  # noqa: BLE001 — migration is best-effort
        pass


def init(db_path: Optional[str] = None) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute(_DDL)
        conn.commit()
        _ensure_columns(conn)
    finally:
        conn.close()


def save_run(
    mode: str,
    company_name: Optional[str] = None,
    ticker: Optional[str] = None,
    sector: Optional[str] = None,
    listing_chapter: Optional[str] = None,
    profile: Optional[str] = None,
    composite_score: Optional[float] = None,
    letter_rating: Optional[str] = None,
    markdown: Optional[str] = None,
    metrics: Any = None,
    source_filenames: Any = None,
    status: str = "pending",
    db_path: Optional[str] = None,
) -> int:
    """Persist one forensic run and return its id.

    ``metrics`` may be a dict (json-encoded) or a pre-encoded string.
    ``source_filenames`` may be a list (json-encoded) or a string. Everything is
    optional except ``mode`` so E0 can round-trip a shell row; later steps fill
    the scored fields. Idempotently ensures the schema exists first.
    """
    init(db_path)
    if isinstance(metrics, (dict, list)):
        metrics_json = json.dumps(metrics)
    else:
        metrics_json = metrics  # already a string or None
    if isinstance(source_filenames, (list, tuple)):
        src = json.dumps(list(source_filenames))
    else:
        src = source_filenames
    conn = get_conn(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO forensic_runs"
            "(created_at,mode,company_name,ticker,sector,listing_chapter,profile,"
            "composite_score,letter_rating,markdown,metrics_json,source_filenames,status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                _now(),
                str(mode) if mode is not None else None,
                company_name,
                ticker,
                sector,
                listing_chapter,
                profile,
                float(composite_score) if composite_score is not None else None,
                letter_rating,
                markdown,
                metrics_json,
                src,
                str(status) if status else "pending",
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_runs(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    init(db_path)
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT id,created_at,mode,company_name,ticker,sector,profile,"
            "composite_score,letter_rating,status FROM forensic_runs "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_run(run_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    init(db_path)
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM forensic_runs WHERE id=?", (int(run_id),)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    out = dict(row)
    out["metrics"] = json.loads(out["metrics_json"]) if out.get("metrics_json") else {}
    return out
