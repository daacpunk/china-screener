"""Tab 4 — Results + optional key-gated LLM analysis."""
from __future__ import annotations

import io

import pandas as pd
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

import markdown as md

from .. import notes_store as ns
from .. import screen_engine as se
from .. import settings_store as ss
from ..llm import analysis as la
from ..llm import research_notes as rn
from ..llm.registry import build_provider
from .common import base_ctx, df_to_records, run_active_screen, templates

router = APIRouter()

# In-memory sidebar synthesis cache keyed by active snapshot id. We only call
# the LLM on a fresh Run Screen / first results load after a run for a given
# snapshot — NOT on every filter change (which just re-reads this cache).
_SIDEBAR_CACHE: dict = {}


def _resolve_sidebar_provider():
    """Build the provider resolved for the 'sidebar' section, key-gated."""
    prov_name = ss.get_section_provider("sidebar")
    key = ss.get_api_key(prov_name)
    cfg = ss.get_provider_config(prov_name)
    if key and cfg["enabled"]:
        return build_provider(prov_name, key, cfg["model"])
    return None


def _resolve_note_provider(provider: str = ""):
    """Provider for a research note, key-gated. An explicit form value wins;
    otherwise fall back to the Results 'sidebar' section provider."""
    prov_name = provider or ss.get_section_provider("sidebar")
    key = ss.get_api_key(prov_name)
    cfg = ss.get_provider_config(prov_name)
    if key and cfg["enabled"]:
        return build_provider(prov_name, key, cfg["model"])
    return None


def _staleness(meta: dict) -> dict:
    """As-of + staleness banner data, mirroring results_page."""
    asof = meta.get("asof")
    staleness_days = int(meta.get("staleness_days", ss.get_screen_params().get("staleness_days", 3)))
    n_stale = se.days_stale(asof) if asof else None
    is_stale = (n_stale is not None) and (n_stale > staleness_days)
    return {"asof": asof, "n_stale": n_stale, "is_stale": is_stale, "staleness_days": staleness_days}


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _sidebar_for(res: dict, force: bool = False) -> dict:
    """Return a rendered sidebar dict {enabled, html, error, provider}.

    Cached by active snapshot id so reloading /results with filters does not
    re-call the LLM. `force=True` recomputes (used on explicit Run Screen).
    Never crashes the page.
    """
    if res.get("_empty"):
        return {"enabled": False, "html": "", "error": "", "provider": None, "empty": True}
    snap = ss.get_active_snapshot()
    snap_id = snap["id"] if snap else None
    if not force and snap_id in _SIDEBAR_CACHE:
        return _SIDEBAR_CACHE[snap_id]
    provider = _resolve_sidebar_provider()
    out = la.synthesize_sidebar(
        provider,
        df_to_records(res["oversold"]),
        df_to_records(res["overbought"]),
        df_to_records(res["master"]),
    )
    html = md.markdown(out["markdown"], extensions=["tables"]) if out.get("markdown") else ""
    rendered = {"enabled": out["enabled"], "html": html,
                "error": out["error"], "provider": out.get("provider"), "empty": False}
    if snap_id is not None:
        _SIDEBAR_CACHE[snap_id] = rendered
    return rendered


def _apply_filters(df: pd.DataFrame, q) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df
    sector = q.get("sector")
    sub = q.get("sub_industry")
    idio = q.get("idio_only")
    hide_event = q.get("hide_event")
    rsi_min = q.get("rsi_min")
    rsi_max = q.get("rsi_max")
    macd_state = q.get("macd_state")
    if sector:
        out = out[out["sector"] == sector]
    if sub:
        out = out[out["sub_industry"] == sub]
    if idio:
        out = out[out["dislocation_type"] == "IDIOSYNCRATIC"]
    if hide_event and "event_flag" in out.columns:
        out = out[~out["event_flag"].astype(bool)]
    if rsi_min not in (None, ""):
        out = out[out["rsi"] >= float(rsi_min)]
    if rsi_max not in (None, ""):
        out = out[out["rsi"] <= float(rsi_max)]
    if macd_state:
        out = out[out["macd_state"] == macd_state]
    return out


@router.get("/results", response_class=HTMLResponse)
def results_page(request: Request):
    res = run_active_screen()
    empty = res.get("_empty", False)
    q = dict(request.query_params)
    oversold = _apply_filters(res["oversold"], q) if not empty else pd.DataFrame()
    overbought = _apply_filters(res["overbought"], q) if not empty else pd.DataFrame()
    master = _apply_filters(res["master"], q) if not empty else pd.DataFrame()
    sectors = sorted([s for s in (res["master"]["sector"].dropna().unique() if not empty else [])])
    subs = sorted([s for s in (res["master"]["sub_industry"].dropna().unique() if not empty else [])])
    providers = ss.list_provider_configs()
    any_key = any(p["has_key"] and p["enabled"] for p in providers)
    # Force a fresh synthesis on an explicit Run Screen (?run=1); otherwise use
    # the snapshot-keyed cache so filter changes don't re-call the LLM.
    force = q.get("run") in ("1", "true", "yes")
    sidebar = _sidebar_for(res, force=force)
    meta = res.get("meta", {}) or {}
    asof = meta.get("asof")
    staleness_days = int(meta.get("staleness_days", ss.get_screen_params().get("staleness_days", 3)))
    n_stale = se.days_stale(asof) if asof else None
    is_stale = (n_stale is not None) and (n_stale > staleness_days)
    snap = ss.get_active_snapshot()
    ctx = base_ctx(
        request, "results", empty=empty,
        oversold=df_to_records(oversold), overbought=df_to_records(overbought),
        master=df_to_records(master), sectors=sectors, subs=subs,
        skipped=df_to_records(res.get("skipped")), filters=q,
        providers=providers, any_key=any_key,
        sidebar=sidebar,
        params=ss.get_screen_params(),
        meta=meta, asof=asof, n_stale=n_stale, is_stale=is_stale,
        staleness_days=staleness_days,
        event_data_loaded=bool(meta.get("event_data_loaded", False)),
        snapshot_uploaded_at=(snap.get("created_at") if snap else None),
    )
    return templates.TemplateResponse(request, "results.html", ctx)


@router.get("/results/export")
def results_export(kind: str = "master"):
    res = run_active_screen()
    if res.get("_empty"):
        return Response("No results", status_code=400)
    df = res.get(kind, res["master"])
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as xw:
        for name in ["master", "oversold", "overbought"]:
            d = res[name]
            (d if not d.empty else pd.DataFrame(columns=["(empty)"])).to_excel(xw, sheet_name=name, index=False)
    return Response(
        content=bio.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=screen_results.xlsx"},
    )


@router.post("/results/analyze", response_class=HTMLResponse)
def results_analyze(request: Request, provider: str = Form("")):
    res = run_active_screen()
    if res.get("_empty"):
        return HTMLResponse("<div class='note error'>No screen results to analyze.</div>")
    prov_name = provider or ss.get_default_provider()
    key = ss.get_api_key(prov_name)
    cfg = ss.get_provider_config(prov_name)
    prov = build_provider(prov_name, key, cfg["model"]) if (key and cfg["enabled"]) else None
    result = la.analyze_rows(prov, df_to_records(res["oversold"]), df_to_records(res["overbought"]))
    return templates.TemplateResponse(request, "partials/analysis.html",
                                      {"analysis": result})


@router.post("/results/note", response_class=HTMLResponse)
def results_note(
    request: Request,
    provider: str = Form(""),
    max_longs: int = Form(2),
    max_shorts: int = Form(2),
    idio_only: str = Form(""),
):
    res = run_active_screen()
    if res.get("_empty"):
        return HTMLResponse("<div class='note error'>No screen results — run a screen first.</div>")
    meta = res.get("meta", {}) or {}
    stale = _staleness(meta)
    prov = _resolve_note_provider(provider)
    out = rn.generate_note(
        prov,
        df_to_records(res["master"]),
        df_to_records(res["oversold"]),
        df_to_records(res["overbought"]),
        ss.get_screen_params(),
        max_longs=max(0, int(max_longs)),
        max_shorts=max(0, int(max_shorts)),
        idio_only=_truthy(idio_only),
        asof=stale["asof"],
    )
    note_id = None
    try:
        note_id = ns.save_note(out.get("asof"), out.get("provider"),
                               out.get("candidates"), out.get("markdown"))
    except Exception:  # noqa: BLE001 — persistence must never crash the screen
        note_id = None
    html = md.markdown(out["markdown"], extensions=["tables"]) if out.get("markdown") else ""
    return templates.TemplateResponse(request, "partials/note.html", {
        "note": {
            "id": note_id, "html": html, "candidates": out.get("candidates") or [],
            "error": out.get("error"), "provider": out.get("provider"),
            "asof": out.get("asof"),
        },
        **stale,
    })


@router.get("/results/note/export")
def results_note_export(id: int):
    note = ns.get_note(id)
    if not note:
        return Response("Note not found", status_code=404)
    asof = note.get("asof") or "unknown"
    fname = f"research_note_{asof}.md".replace(" ", "_").replace(":", "")
    return Response(
        content=note.get("markdown") or "",
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.get("/results/notes", response_class=HTMLResponse)
def results_notes_list(request: Request):
    notes = ns.list_notes(limit=50)
    return templates.TemplateResponse(request, "partials/notes_list.html",
                                      {"notes": notes})
