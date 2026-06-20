"""Settings + versioned-asset persistence layer over SQLite.

Handles screen params, encrypted API keys (env-first), dictionary versions,
universe versions, and price snapshots. No web deps.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import crypto
from .db import get_conn
from .llm.models import DEFAULT_MODEL as _DEFAULT_MODEL
from .llm.models import estimate_cost as _estimate_cost
from .screen_engine import DEFAULT_PARAMS

_PROVIDERS = ["perplexity", "anthropic", "deepseek"]
_ENV_KEY = {
    "perplexity": "PERPLEXITY_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

_PARAMS_KEY = "screen_params"

# Per-section AI provider override keys (CHANGE 4).
SECTIONS = ["per_name", "portfolio", "sidebar", "news"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Screen params
# ---------------------------------------------------------------------------
def get_screen_params(db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (_PARAMS_KEY,)).fetchone()
        params = dict(DEFAULT_PARAMS)
        if row and row["value"]:
            try:
                params.update(json.loads(row["value"]))
            except Exception:
                pass
        return params
    finally:
        conn.close()


def set_screen_params(params: Dict[str, Any], db_path: Optional[str] = None) -> None:
    merged = dict(DEFAULT_PARAMS)
    merged.update({k: v for k, v in params.items() if v is not None})
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_PARAMS_KEY, json.dumps(merged)),
        )
        conn.commit()
    finally:
        conn.close()


def reset_screen_params(db_path: Optional[str] = None) -> None:
    set_screen_params(dict(DEFAULT_PARAMS), db_path)


# ---------------------------------------------------------------------------
# API keys (env first, then encrypted SQLite)
# ---------------------------------------------------------------------------
def set_api_key(
    provider: str,
    key: str,
    model: Optional[str] = None,
    enabled: Optional[bool] = None,
    db_path: Optional[str] = None,
) -> None:
    if provider not in _PROVIDERS:
        raise ValueError(f"unknown provider {provider}")
    conn = get_conn(db_path)
    try:
        existing = conn.execute(
            "SELECT model, enabled, enc_value FROM api_keys WHERE provider=?", (provider,)
        ).fetchone()
        enc = crypto.encrypt(key) if key else (existing["enc_value"] if existing else "")
        mdl = model or (existing["model"] if existing else _DEFAULT_MODEL[provider])
        en = int(enabled) if enabled is not None else (existing["enabled"] if existing else 0)
        conn.execute(
            "INSERT INTO api_keys(provider,enc_value,model,enabled,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(provider) DO UPDATE SET "
            "enc_value=excluded.enc_value, model=excluded.model, "
            "enabled=excluded.enabled, updated_at=excluded.updated_at",
            (provider, enc, mdl, en, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def get_api_key(provider: str, db_path: Optional[str] = None) -> str:
    """Return decrypted key — env var takes precedence over stored value."""
    env_val = os.environ.get(_ENV_KEY.get(provider, ""), "").strip()
    if env_val:
        return env_val
    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT enc_value FROM api_keys WHERE provider=?", (provider,)).fetchone()
        if row and row["enc_value"]:
            return crypto.decrypt(row["enc_value"])
        return ""
    finally:
        conn.close()


def get_provider_config(provider: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT model, enabled, updated_at FROM api_keys WHERE provider=?", (provider,)
        ).fetchone()
    finally:
        conn.close()
    key = get_api_key(provider, db_path)
    env_set = bool(os.environ.get(_ENV_KEY.get(provider, ""), "").strip())
    return {
        "provider": provider,
        "model": (row["model"] if row else None) or _DEFAULT_MODEL[provider],
        "enabled": bool(row["enabled"]) if row else False,
        "has_key": bool(key),
        "key_source": "env" if env_set else ("store" if key else "none"),
        "masked": crypto.mask(key),
        "updated_at": row["updated_at"] if row else None,
    }


def list_provider_configs(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    return [get_provider_config(p, db_path) for p in _PROVIDERS]


def get_default_provider(db_path: Optional[str] = None) -> str:
    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key='default_provider'").fetchone()
        if row and row["value"] in _PROVIDERS:
            return row["value"]
    finally:
        conn.close()
    return "perplexity"


def set_default_provider(provider: str, db_path: Optional[str] = None) -> None:
    if provider not in _PROVIDERS:
        raise ValueError(provider)
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('default_provider',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (provider,),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Per-section AI provider (CHANGE 4)
# ---------------------------------------------------------------------------
def _section_key(section: str) -> str:
    return f"section_provider:{section}"


def get_section_provider(section: str, db_path: Optional[str] = None) -> str:
    """Resolved provider for a section; falls back to the global default."""
    if section not in SECTIONS:
        raise ValueError(f"unknown section {section}")
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (_section_key(section),)
        ).fetchone()
        if row and row["value"] in _PROVIDERS:
            return row["value"]
    finally:
        conn.close()
    return get_default_provider(db_path)


def set_section_provider(section: str, provider: str, db_path: Optional[str] = None) -> None:
    """Set a section provider. Pass '' or None to clear (use global default)."""
    if section not in SECTIONS:
        raise ValueError(f"unknown section {section}")
    conn = get_conn(db_path)
    try:
        if not provider:
            conn.execute("DELETE FROM settings WHERE key=?", (_section_key(section),))
        else:
            if provider not in _PROVIDERS:
                raise ValueError(f"unknown provider {provider}")
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_section_key(section), provider),
            )
        conn.commit()
    finally:
        conn.close()


def get_section_provider_raw(section: str, db_path: Optional[str] = None) -> Optional[str]:
    """The stored override (or None if unset). Used by the UI to show the
    '(use global default)' selection vs an explicit override."""
    if section not in SECTIONS:
        raise ValueError(f"unknown section {section}")
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (_section_key(section),)
        ).fetchone()
        if row and row["value"] in _PROVIDERS:
            return row["value"]
        return None
    finally:
        conn.close()


def get_all_section_providers(db_path: Optional[str] = None) -> Dict[str, str]:
    """Resolved provider per section (with global fallback applied)."""
    return {s: get_section_provider(s, db_path) for s in SECTIONS}


# ---------------------------------------------------------------------------
# Dictionary versioning
# ---------------------------------------------------------------------------
def validate_dictionary(json_text: str) -> Dict[str, Any]:
    """Validate dictionary JSON. Returns parsed dict or raises ValueError."""
    try:
        data = json.loads(json_text)
    except Exception as e:
        raise ValueError(f"Invalid JSON: {e}")
    if not isinstance(data, dict) or "formulas" not in data:
        raise ValueError("Dictionary must be an object with a 'formulas' map")
    formulas = data["formulas"]
    if not isinstance(formulas, dict) or not formulas:
        raise ValueError("'formulas' must be a non-empty object")
    for key, val in formulas.items():
        if not isinstance(val, dict) or "fql_template" not in val:
            raise ValueError(f"Formula '{key}' missing 'fql_template'")
    return data


def add_dictionary(
    json_text: str, md_text: str = "", filename: str = "", note: str = "",
    make_active: bool = True, db_path: Optional[str] = None,
) -> Dict[str, Any]:
    parsed = validate_dictionary(json_text)  # raises on bad
    prev = get_active_dictionary(db_path)
    conn = get_conn(db_path)
    try:
        if make_active:
            conn.execute("UPDATE dictionaries SET is_active=0")
        cur = conn.execute(
            "INSERT INTO dictionaries(filename,note,json_text,md_text,created_at,is_active) "
            "VALUES(?,?,?,?,?,?)",
            (filename, note, json_text, md_text, _now(), int(make_active)),
        )
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()
    diff = _dict_diff(prev["data"] if prev else None, parsed)
    return {"id": new_id, "diff": diff}


def _dict_diff(old: Optional[dict], new: dict) -> Dict[str, List[str]]:
    new_keys = set(new.get("formulas", {}).keys())
    old_keys = set((old or {}).get("formulas", {}).keys()) if old else set()
    return {
        "added": sorted(new_keys - old_keys),
        "removed": sorted(old_keys - new_keys),
        "unchanged": sorted(new_keys & old_keys),
    }


def list_dictionaries(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT id,filename,note,created_at,is_active FROM dictionaries ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_active_dictionary(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM dictionaries WHERE is_active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["json_text"])
        except Exception:
            data = {"formulas": {}}
        return {
            "id": row["id"], "filename": row["filename"], "note": row["note"],
            "created_at": row["created_at"], "data": data,
            "md_text": row["md_text"] or "", "json_text": row["json_text"],
        }
    finally:
        conn.close()


def set_active_dictionary(dict_id: int, db_path: Optional[str] = None) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute("UPDATE dictionaries SET is_active=0")
        conn.execute("UPDATE dictionaries SET is_active=1 WHERE id=?", (dict_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Universe versioning
# ---------------------------------------------------------------------------
def add_universe(
    csv_text: str, manual_csv: str = "", filename: str = "", note: str = "",
    make_active: bool = True, db_path: Optional[str] = None,
) -> int:
    conn = get_conn(db_path)
    try:
        if make_active:
            conn.execute("UPDATE universes SET is_active=0")
        cur = conn.execute(
            "INSERT INTO universes(filename,note,csv_text,manual_csv,created_at,is_active) "
            "VALUES(?,?,?,?,?,?)",
            (filename, note, csv_text, manual_csv, _now(), int(make_active)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_universes(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT id,filename,note,created_at,is_active FROM universes ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_active_universe(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Active universe = the version flagged is_active (the user's explicit pin,
    or the most recent upload, which is auto-activated on add). If no row is
    flagged active but versions exist (e.g. a legacy/migrated DB), fall back to
    the newest version so the latest upload is always the default."""
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM universes WHERE is_active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM universes ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def ensure_active_universe(db_path: Optional[str] = None) -> Optional[int]:
    """Guarantee exactly the newest universe is active when none is pinned.

    Called on startup. If versions exist but none is flagged is_active, promote
    the most recent one so the latest uploaded universe is the persisted default
    after a restart/redeploy. Returns the active universe id (or None if empty).
    """
    conn = get_conn(db_path)
    try:
        active = conn.execute(
            "SELECT id FROM universes WHERE is_active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if active is not None:
            return int(active["id"])
        newest = conn.execute(
            "SELECT id FROM universes ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if newest is None:
            return None
        conn.execute("UPDATE universes SET is_active=0")
        conn.execute("UPDATE universes SET is_active=1 WHERE id=?", (newest["id"],))
        conn.commit()
        return int(newest["id"])
    finally:
        conn.close()


def set_active_universe(uid: int, db_path: Optional[str] = None) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute("UPDATE universes SET is_active=0")
        conn.execute("UPDATE universes SET is_active=1 WHERE id=?", (uid,))
        conn.commit()
    finally:
        conn.close()


def update_universe_manual(uid: int, manual_csv: str, db_path: Optional[str] = None) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute("UPDATE universes SET manual_csv=? WHERE id=?", (manual_csv, uid))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Price snapshots
# ---------------------------------------------------------------------------
def add_snapshot(
    csv_text: str, quality_json: str = "", filename: str = "", note: str = "",
    make_active: bool = True, db_path: Optional[str] = None,
) -> int:
    conn = get_conn(db_path)
    try:
        if make_active:
            conn.execute("UPDATE snapshots SET is_active=0")
        cur = conn.execute(
            "INSERT INTO snapshots(filename,note,csv_text,quality_json,created_at,is_active) "
            "VALUES(?,?,?,?,?,?)",
            (filename, note, csv_text, quality_json, _now(), int(make_active)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_snapshots(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT id,filename,note,created_at,is_active FROM snapshots ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_active_snapshot(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE is_active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_active_snapshot(sid: int, db_path: Optional[str] = None) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute("UPDATE snapshots SET is_active=0")
        conn.execute("UPDATE snapshots SET is_active=1 WHERE id=?", (sid,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# LLM usage / cost audit ledger
# ---------------------------------------------------------------------------
USAGE_SECTIONS = ["per_name", "portfolio", "sidebar", "news", "ping", "manual"]


def log_usage(
    provider: str,
    model: str,
    section: str,
    usage_dict: Optional[Dict[str, Any]],
    ok: bool = True,
    note: str = "",
    db_path: Optional[str] = None,
) -> None:
    """Append one row to the llm_usage ledger. Computes est cost via pricing.

    ``usage_dict`` is the provider's ``last_usage`` ({prompt_tokens,
    completion_tokens}) or None. Tolerant of None / missing keys.
    """
    u = usage_dict or {}
    try:
        pt = int(u.get("prompt_tokens", 0) or 0)
    except Exception:
        pt = 0
    try:
        ct = int(u.get("completion_tokens", 0) or 0)
    except Exception:
        ct = 0
    total = pt + ct
    est = _estimate_cost(model or "", pt, ct)
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO llm_usage(ts,provider,model,section,prompt_tokens,"
            "completion_tokens,total_tokens,est_cost_usd,ok,note) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (_now(), provider or "", model or "", section or "manual",
             pt, ct, total, float(est), int(bool(ok)), (note or "")[:500]),
        )
        conn.commit()
    finally:
        conn.close()


def get_usage_summary(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Return aggregates + per-provider/model/section breakdown."""
    conn = get_conn(db_path)
    try:
        tot = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(total_tokens),0) t, "
            "COALESCE(SUM(est_cost_usd),0) cost, COALESCE(SUM(prompt_tokens),0) pt, "
            "COALESCE(SUM(completion_tokens),0) ct FROM llm_usage"
        ).fetchone()
        breakdown = conn.execute(
            "SELECT provider, model, section, COUNT(*) calls, "
            "COALESCE(SUM(total_tokens),0) tokens, "
            "COALESCE(SUM(est_cost_usd),0) cost, "
            "SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) fails "
            "FROM llm_usage GROUP BY provider, model, section "
            "ORDER BY cost DESC, tokens DESC"
        ).fetchall()
    finally:
        conn.close()
    return {
        "total_calls": int(tot["c"]),
        "total_tokens": int(tot["t"]),
        "total_prompt_tokens": int(tot["pt"]),
        "total_completion_tokens": int(tot["ct"]),
        "total_cost_usd": float(tot["cost"]),
        "breakdown": [
            {
                "provider": r["provider"], "model": r["model"],
                "section": r["section"], "calls": int(r["calls"]),
                "tokens": int(r["tokens"]), "cost_usd": float(r["cost"]),
                "fails": int(r["fails"] or 0),
            }
            for r in breakdown
        ],
    }


def recent_usage(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Most-recent ledger rows for a detail table."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT ts,provider,model,section,prompt_tokens,completion_tokens,"
            "total_tokens,est_cost_usd,ok,note FROM llm_usage "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def clear_usage(db_path: Optional[str] = None) -> int:
    """Delete all ledger rows. Returns number removed."""
    conn = get_conn(db_path)
    try:
        cur = conn.execute("DELETE FROM llm_usage")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
