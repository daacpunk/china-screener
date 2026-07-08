"""Tab 5 — Analysis: key-gated AI synthesis + research-note generator.

Runs the SAME active screen as the Results Data page (common.run_active_screen)
so AI analysis and notes operate on the current screen output. All LLM paths are
key-gated and crash-proof; export paths degrade gracefully on empty markdown.
"""
from __future__ import annotations

from typing import Optional

import markdown as md
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from .. import exporters
from .. import notes_store as ns
from .. import screen_engine as se
from .. import settings_store as ss
from ..llm import analysis as la
from ..llm import research_notes as rn
from ..llm.base import LLMProvider
from ..llm.registry import build_provider
from ..llm.research_notes import is_web_capable
from . import jobs
from .common import base_ctx, df_to_records, run_active_screen, templates
from .routes_results import _SIDEBAR_CACHE

router = APIRouter()


def resolve_web_provider() -> Optional[LLMProvider]:
    """Build a PERPLEXITY provider for the per-name web (catalyst) triage,
    independent of the chosen synthesis provider (mirrors routes_weekly).

    Returns a built Perplexity provider when a Perplexity API key exists AND the
    Perplexity provider config is enabled; otherwise None. The returned provider
    is sanity-checked with ``is_web_capable``. Never raises.
    """
    try:
        key = ss.get_api_key("perplexity")
        if not key:
            return None
        cfg = ss.get_provider_config("perplexity")
        if not cfg.get("enabled"):
            return None
        prov = build_provider("perplexity", key, cfg.get("model") or "")
        if prov is None or not is_web_capable(prov):
            return None
        return prov
    except Exception:  # noqa: BLE001 — web provider resolution must never crash
        return None


def build_fallback_providers(primary_name: str) -> list:
    """Built providers for every OTHER configured provider that is enabled and
    has a key, EXCLUDING the primary. This is the fallback pool used when the
    primary stays overloaded. Skips any that fail to build."""
    out = []
    for cfg in ss.list_provider_configs():
        name = cfg["provider"]
        if name == primary_name or not (cfg["enabled"] and cfg["has_key"]):
            continue
        try:
            key = ss.get_api_key(name)
            prov = build_provider(name, key, cfg["model"])
            if prov is not None:
                out.append(prov)
        except Exception:  # noqa: BLE001 — a bad fallback must never crash the screen
            continue
    return out


def _resolve_sidebar_provider():
    prov_name = ss.get_section_provider("sidebar")
    key = ss.get_api_key(prov_name)
    cfg = ss.get_provider_config(prov_name)
    if key and cfg["enabled"]:
        return build_provider(prov_name, key, cfg["model"])
    return None


def _resolve_note_provider(provider: str = ""):
    """An explicit form value wins; otherwise fall back to the 'sidebar' provider."""
    prov_name = provider or ss.get_section_provider("sidebar")
    key = ss.get_api_key(prov_name)
    cfg = ss.get_provider_config(prov_name)
    if key and cfg["enabled"]:
        return build_provider(prov_name, key, cfg["model"])
    return None


def _staleness(meta: dict) -> dict:
    asof = meta.get("asof")
    staleness_days = int(meta.get("staleness_days", ss.get_screen_params().get("staleness_days", 3)))
    n_stale = se.days_stale(asof) if asof else None
    is_stale = (n_stale is not None) and (n_stale > staleness_days)
    return {"asof": asof, "n_stale": n_stale, "is_stale": is_stale, "staleness_days": staleness_days}


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _sidebar_for(res: dict, force: bool = False) -> dict:
    """Rendered sidebar dict {enabled, html, error, provider}. Cached by active
    snapshot id so reloading Analysis doesn't re-call the LLM. Never crashes."""
    if res.get("_empty"):
        return {"enabled": False, "html": "", "error": "", "provider": None, "empty": True}
    snap = ss.get_active_snapshot()
    snap_id = snap["id"] if snap else None
    if not force and snap_id in _SIDEBAR_CACHE:
        return _SIDEBAR_CACHE[snap_id]
    provider = _resolve_sidebar_provider()
    fallbacks = build_fallback_providers(getattr(provider, "name", "")) if provider else []
    out = la.synthesize_sidebar(
        provider,
        df_to_records(res["oversold"]),
        df_to_records(res["overbought"]),
        df_to_records(res["master"]),
        fallback_providers=fallbacks,
    )
    html = md.markdown(out["markdown"], extensions=["tables"]) if out.get("markdown") else ""
    rendered = {"enabled": out["enabled"], "html": html,
                "error": out["error"], "provider": out.get("provider"), "empty": False}
    if snap_id is not None:
        _SIDEBAR_CACHE[snap_id] = rendered
    return rendered


@router.get("/analysis", response_class=HTMLResponse)
def analysis_page(request: Request):
    res = run_active_screen()
    empty = res.get("_empty", False)
    providers = ss.list_provider_configs()
    any_key = any(p["has_key"] and p["enabled"] for p in providers)
    q = dict(request.query_params)
    force = q.get("run") in ("1", "true", "yes")
    sidebar = _sidebar_for(res, force=force) if not empty else {
        "enabled": False, "html": "", "error": "", "provider": None, "empty": True}
    meta = res.get("meta", {}) or {}
    stale = _staleness(meta)
    note_provider = ss.get_section_provider("sidebar")
    # A dedicated Perplexity web provider fires the catalyst triage independently
    # of the chosen synthesis model. Default the web checkbox on when EITHER the
    # chosen synthesis provider is Perplexity OR a Perplexity key is set.
    web_provider = resolve_web_provider()
    perplexity_web_ready = web_provider is not None
    note_web_default = (str(note_provider).lower() == "perplexity") or perplexity_web_ready
    ctx = base_ctx(
        request, "analysis", empty=empty,
        providers=providers, any_key=any_key,
        sidebar=sidebar, note_web_default=note_web_default,
        perplexity_web_ready=perplexity_web_ready,
        **stale,
    )
    return templates.TemplateResponse(request, "analysis.html", ctx)


@router.post("/analysis/analyze", response_class=HTMLResponse)
def analysis_analyze(request: Request, provider: str = Form("")):
    res = run_active_screen()
    if res.get("_empty"):
        return HTMLResponse("<div class='note error'>No screen results to analyze.</div>")
    prov_name = provider or ss.get_default_provider()
    key = ss.get_api_key(prov_name)
    cfg = ss.get_provider_config(prov_name)
    prov = build_provider(prov_name, key, cfg["model"]) if (key and cfg["enabled"]) else None
    fallbacks = build_fallback_providers(prov_name) if prov else []
    result = la.analyze_rows(
        prov, df_to_records(res["oversold"]), df_to_records(res["overbought"]),
        max_workers=4, fallback_providers=fallbacks,
    )
    return templates.TemplateResponse(request, "partials/analysis.html", {"analysis": result})


def _note_job(prov, master, oversold, overbought, params, max_longs, max_shorts,
              idio_only, wn, asof, fallbacks, web_provider) -> dict:
    """Self-contained SLOW work run on a background thread: LLM note generation,
    persistence, and markdown render. Returns a plain DATA dict — the status
    route builds the Jinja TemplateResponse on the request thread (Jinja needs
    the request). Never renders here. rn.generate_note itself never raises.
    """
    out = rn.generate_note(
        prov, master, oversold, overbought, params,
        max_longs=max_longs, max_shorts=max_shorts, idio_only=idio_only,
        with_news=wn, asof=asof, fallback_providers=fallbacks,
        web_provider=web_provider,
    )
    note_id = None
    try:
        note_id = ns.save_note(out.get("asof"), out.get("provider"),
                               out.get("candidates"), out.get("markdown"))
    except Exception:  # noqa: BLE001 — persistence must never crash the job
        note_id = None
    html = md.markdown(out["markdown"], extensions=["tables"]) if out.get("markdown") else ""
    return {
        "note_id": note_id, "html": html, "candidates": out.get("candidates") or [],
        "error": out.get("error"), "provider": out.get("provider"),
        "asof": out.get("asof"), "notice": out.get("notice"),
    }


def _render_note(request: Request, data: dict, stale: dict) -> HTMLResponse:
    """Render the FINAL note partial (no poller) from a job-result data dict."""
    return templates.TemplateResponse(request, "partials/note.html", {
        "note": {
            "id": data.get("note_id"), "html": data.get("html", ""),
            "candidates": data.get("candidates") or [],
            "error": data.get("error"), "provider": data.get("provider"),
            "asof": data.get("asof"), "notice": data.get("notice"),
        },
        **stale,
    })


def _generate_note(request: Request, provider: str, max_longs: int,
                   max_shorts: int, idio_only: str, with_news: str) -> HTMLResponse:
    # FAST prep on the request thread: read the active screen + resolve providers.
    res = run_active_screen()
    if res.get("_empty"):
        return HTMLResponse("<div class='note error'>No screen results — run a screen first.</div>")
    meta = res.get("meta", {}) or {}
    stale = _staleness(meta)
    prov = _resolve_note_provider(provider)
    fallbacks = build_fallback_providers(getattr(prov, "name", "")) if prov else []
    # The section picker chooses the SYNTHESIS model; the web catalyst triage
    # always routes to Perplexity when a Perplexity key is set (split provider).
    web_provider = resolve_web_provider()
    # Default with_news on when EITHER the synthesis provider or the dedicated
    # Perplexity web provider can ground catalysts in live web search.
    wn = _truthy(with_news) if str(with_news).strip() != "" else (
        is_web_capable(prov) or is_web_capable(web_provider)
    )
    # Pull plain records on the REQUEST thread; the worker only does LLM + persist
    # + render, never touches the DataFrame/screen read.
    master = df_to_records(res["master"])
    oversold = df_to_records(res["oversold"])
    overbought = df_to_records(res["overbought"])
    params = ss.get_screen_params()
    ml = max(0, int(max_longs))
    msh = max(0, int(max_shorts))
    idio = _truthy(idio_only)

    # FAST PATH: no provider -> generate_note returns instantly (candidates +
    # set-a-key error). Skip the background job and render inline as before.
    if prov is None or not getattr(prov, "available", False):
        data = _note_job(prov, master, oversold, overbought, params, ml, msh,
                         idio, wn, stale["asof"], fallbacks, web_provider)
        return _render_note(request, data, stale)

    # SLOW PATH: kick off the LLM work in a background job and return the polling
    # partial immediately so the HTTP request never exceeds the edge timeout.
    job_id = jobs.start_job(
        _note_job, prov, master, oversold, overbought, params, ml, msh,
        idio, wn, stale["asof"], fallbacks, web_provider,
    )
    return templates.TemplateResponse(request, "partials/note_pending.html", {
        "job_id": job_id, **stale,
    })


@router.get("/analysis/note/status", response_class=HTMLResponse)
def analysis_note_status(request: Request, job: str = ""):
    """Poll target for the background research-note job.

    running -> the SAME pending partial (keeps polling);
    done    -> the FINAL note partial (no poller, polling stops);
    error   -> a clean error partial (no poller);
    unknown -> a gentle 'note expired, please regenerate' partial (no poller).
    """
    # Staleness is recomputed from the current active screen for the final render.
    res = run_active_screen()
    meta = res.get("meta", {}) or {}
    stale = _staleness(meta)
    rec = jobs.get_job(job)
    if rec is None:
        # Unknown/expired: replace the whole poller (stops polling) via OOB swap.
        return HTMLResponse(
            "<div id='note-poll' hx-swap-oob='outerHTML:#note-poll'>"
            "<div class='note info'>This note request expired — please regenerate.</div>"
            "</div>"
        )
    status = rec.get("status")
    if status == "running":
        # Still running: swap ONLY the inner spinner; the outer #note-poll (with
        # its poll trigger) stays put and keeps polling reliably.
        return templates.TemplateResponse(
            request, "partials/note_pending_inner.html", {}
        )
    if status == "error":
        emsg = rec.get("error") or "generation failed"
        # Replace the whole poller (removes trigger -> stops polling) via OOB.
        return HTMLResponse(
            "<div id='note-poll' hx-swap-oob='outerHTML:#note-poll'>"
            f"<div class='note error'>Research note generation failed: {emsg}</div>"
            "</div>"
        )
    # done: render the final note and REPLACE the whole #note-poll via an OOB
    # swap so the poll trigger is removed and the report is shown. The normal
    # (targeted) response body is empty; the OOB fragment carries the note.
    data = rec.get("result") or {}
    note_html = _render_note(request, data, stale).body.decode("utf-8")
    return HTMLResponse(
        f"<div id='note-poll' hx-swap-oob='outerHTML:#note-poll'>{note_html}</div>"
    )


@router.post("/analysis/note", response_class=HTMLResponse)
def analysis_note(
    request: Request,
    provider: str = Form(""),
    max_longs: int = Form(2),
    max_shorts: int = Form(2),
    idio_only: str = Form(""),
    with_news: str = Form(""),
):
    return _generate_note(request, provider, max_longs, max_shorts, idio_only, with_news)


@router.get("/analysis/notes", response_class=HTMLResponse)
def analysis_notes_list(request: Request):
    notes = ns.list_notes(limit=50)
    return templates.TemplateResponse(request, "partials/notes_list.html", {"notes": notes})


@router.get("/analysis/note/export")
def analysis_note_export(id: int, fmt: str = "md"):
    note = ns.get_note(id)
    if not note:
        return Response("Note not found", status_code=404)
    try:
        data, ctype, fname = exporters.export(note, fmt)
    except ValueError:
        return Response("Unknown format", status_code=400)
    return Response(
        content=data,
        media_type=ctype,
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ---- Back-compat aliases: keep the old /results/* note paths working ----
@router.post("/results/note", response_class=HTMLResponse)
def results_note(
    request: Request,
    provider: str = Form(""),
    max_longs: int = Form(2),
    max_shorts: int = Form(2),
    idio_only: str = Form(""),
    with_news: str = Form(""),
):
    return _generate_note(request, provider, max_longs, max_shorts, idio_only, with_news)


@router.get("/results/notes", response_class=HTMLResponse)
def results_notes_list(request: Request):
    return analysis_notes_list(request)


@router.get("/results/note/export")
def results_note_export(id: int, fmt: str = "md"):
    return analysis_note_export(id, fmt)
