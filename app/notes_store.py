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


def _json_safe(obj: Any) -> Any:
    """Fallback serializer for values json.dumps can't handle natively.

    Candidate/metric rows can contain pandas NaT / NaN, pandas Timestamps, and
    numpy scalar types (event_date, earnings_date, z-scores, etc.). Left as-is
    these raise `TypeError: Object of type NaTType is not JSON serializable`,
    which previously crashed save_note and silently prevented notes from being
    persisted. Convert missing/temporal/numpy values to JSON-native forms.
    """
    # Missing values (pandas NaT, float nan) -> null.
    try:
        import math
        if obj is None:
            return None
        if isinstance(obj, float) and math.isnan(obj):
            return None
    except Exception:  # noqa: BLE001
        pass
    # pandas / numpy: NaT, Timestamp, numpy scalars.
    try:
        import pandas as pd
        if obj is pd.NaT or (obj is not None and pd.isna(obj) is True):
            return None
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except Exception:  # noqa: BLE001 — pd.isna raises on some types; ignore
        pass
    try:
        import numpy as np
        if isinstance(obj, np.generic):
            return obj.item()
    except Exception:  # noqa: BLE001
        pass
    # Datetime-like with isoformat.
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:  # noqa: BLE001
            pass
    return str(obj)


def _clean_nan(obj: Any) -> Any:
    """Recursively replace float NaN/inf with None so output is valid JSON."""
    import math
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_nan(v) for v in obj]
    return obj


def _dumps(value: Any) -> Optional[str]:
    """json.dumps that never crashes on NaT/NaN/numpy/Timestamp values and
    always emits valid JSON (NaN/inf -> null via allow_nan=False + cleaning)."""
    if value is None:
        return None
    try:
        return json.dumps(_clean_nan(value), default=_json_safe, allow_nan=False)
    except (ValueError, TypeError):
        # Last resort: stringify anything still unserializable.
        return json.dumps(value, default=lambda o: None, allow_nan=True)


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
                _dumps(candidates),
                markdown or "",
                _dumps(council),
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
