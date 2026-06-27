"""Tab 6 — Weekly Note (Phase D): a fully-isolated HSI-universe vertical.

Independent from the MSCI China screen. End-to-end flow:
  (a) upload a 2-column ticker list (Symbol + FactSet ticker)  -> weekly_universe
  (b) download a pre-built FactSet template (xlsx or batched ZIP)
  (c) upload the populated workbook                            -> weekly_snapshots
  (d) generate the one-pager (data + web catalysts + HSI macro) -> weekly_notes
  (e) view / export (md/html/docx/pdf) and browse past notes.

Every LLM path is key-gated and crash-proof (reuses the analysis provider
resolution + retry/fallback). The page renders clean empty states on a fresh DB.
"""
from __future__ import annotations

import io
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .. import data_ingest as di
from .. import exporters
from .. import settings_store as ss
from ..weekly import ingest as wing
from ..weekly import metrics as wmetrics
from ..weekly import note as wnote
from ..weekly import note_store as wnotes
from ..weekly import snapshot_store as wsnap
from ..weekly import template_gen as wtpl
from ..weekly import universe_store as wuni
from .common import base_ctx, templates
from .routes_analysis import _resolve_note_provider, build_fallback_providers
from ..llm.research_notes import is_web_capable

router = APIRouter()

_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# 2-column ticker-list parsing (Symbol + FactSet ticker)
# ---------------------------------------------------------------------------
_SYMBOL_ALIASES = ["symbol", "name", "ticker", "display", "stock", "company", "security"]
_FACTSET_ALIASES = ["factset ticker", "fs ticker", "factset", "fsym", "fsym_id",
                    "identifier", "fds", "factset_ticker", "id", "ticker"]


def parse_weekly_universe(
    content: bytes, filename: str = "",
    symbol_col: str = "", factset_col: str = "",
) -> Dict[str, Any]:
    """Parse a 2-column ticker list into {rows, mapping, columns_seen, n}.

    ``rows`` is a list of {"symbol","factset_ticker"}. Auto-detects the two
    columns (Symbol = display label; FactSet ticker = used in formulas) with
    optional explicit overrides. Never raises — returns {error} on a bad file.
    """
    try:
        raw = di._read_any(content, filename)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not read the file: {e}", "rows": [],
                "mapping": {}, "columns_seen": [], "n": 0}
    df = di._norm_cols(raw)
    cols = list(df.columns)
    sym = symbol_col.strip().lower() if symbol_col.strip() else di._find_col(cols, _SYMBOL_ALIASES)
    fs = factset_col.strip().lower() if factset_col.strip() else di._find_col(cols, _FACTSET_ALIASES)

    # If both resolved to the same single column, treat it as the FactSet ticker
    # and mirror it into the symbol.
    if fs and sym == fs and len(cols) >= 2:
        # prefer a different column for the symbol if one exists
        other = [c for c in cols if c != fs]
        sym = di._find_col(other, _SYMBOL_ALIASES) or other[0]
    if not fs and sym:
        fs = sym  # single identifier column: use it for both
    if not fs and cols:
        fs = cols[0]
    if not sym:
        sym = fs

    rows: List[Dict[str, str]] = []
    if fs and fs in df.columns:
        for _, r in df.iterrows():
            fval = str(r.get(fs) or "").strip()
            sval = str(r.get(sym) or "").strip() if sym in df.columns else ""
            if not fval or fval.lower() == "nan":
                continue
            rows.append({"symbol": sval or fval, "factset_ticker": fval})
    return {
        "rows": rows,
        "mapping": {"symbol": sym, "factset_ticker": fs},
        "columns_seen": cols,
        "n": len(rows),
    }


# ---------------------------------------------------------------------------
# Page context assembly
# ---------------------------------------------------------------------------
def _active_metrics() -> Optional[Dict[str, Any]]:
    snap = wsnap.get_active()
    if not snap or not snap.get("data"):
        return None
    try:
        return wmetrics.compute_weekly_metrics(snap["data"])
    except Exception:  # noqa: BLE001 — never break the page
        return None


def _weekly_ctx(request: Request, **extra) -> Dict[str, Any]:
    uni = wuni.get_active()
    uni_rows = uni.get("rows", []) if uni else []
    snap = wsnap.get_active()
    snap_data = snap.get("data", {}) if snap else {}
    metrics = _active_metrics()
    providers = ss.list_provider_configs()
    any_key = any(p["has_key"] and p["enabled"] for p in providers)
    note_provider = ss.get_section_provider("sidebar")
    note_web_default = (str(note_provider).lower() == "perplexity")
    ctx = base_ctx(
        request, "weekly",
        universe=uni, universe_rows=uni_rows, n_universe=len(uni_rows),
        universe_versions=wuni.list_universes(),
        snapshot=snap, snapshot_meta=(snap_data.get("meta") if snap_data else None),
        snapshot_versions=wsnap.list_snapshots(),
        metrics=metrics,
        providers=providers, any_key=any_key,
        note_web_default=note_web_default,
        past_notes=wnotes.list_notes(limit=25),
        depth=wtpl.DEPTH, batch_size=wtpl.BATCH_SIZE,
        hsi_id=wtpl.HSI_FACTSET_ID,
    )
    ctx.update(extra)
    return ctx


@router.get("/weekly", response_class=HTMLResponse)
def weekly_page(request: Request):
    return templates.TemplateResponse(request, "weekly.html", _weekly_ctx(request))


# ---------------------------------------------------------------------------
# (a) Ticker-list upload
# ---------------------------------------------------------------------------
@router.post("/weekly/universe/upload")
async def weekly_universe_upload(
    file: UploadFile = File(...),
    symbol_col: str = Form(""),
    factset_col: str = Form(""),
    note: str = Form(""),
):
    content = await file.read()
    parsed = parse_weekly_universe(content, file.filename or "", symbol_col, factset_col)
    if parsed.get("error"):
        return RedirectResponse(f"/weekly?err={quote(parsed['error'][:300])}", status_code=303)
    if parsed["n"] == 0:
        seen = ", ".join(str(c) for c in parsed.get("columns_seen", [])) or "(none)"
        msg = (f"0 names imported. Need a FactSet-ticker column. Columns found: "
               f"[{seen}]. Use the column mapping to point at Symbol + FactSet ticker.")
        return RedirectResponse(f"/weekly?err={quote(msg[:400])}", status_code=303)
    wuni.save_universe(parsed["rows"], name=(note or file.filename or "weekly universe"),
                       make_active=True)
    m = parsed["mapping"]
    msg = (f"Imported {parsed['n']} names from {file.filename}. "
           f"Mapped: symbol←{m.get('symbol')}, factset_ticker←{m.get('factset_ticker')}.")
    return RedirectResponse(f"/weekly?msg={quote(msg[:400])}", status_code=303)


@router.post("/weekly/universe/activate")
def weekly_universe_activate(uid: int = Form(...)):
    wuni.set_active(uid)
    return RedirectResponse("/weekly", status_code=303)


# ---------------------------------------------------------------------------
# (b) Template download
# ---------------------------------------------------------------------------
@router.post("/weekly/template")
def weekly_template(as_zip: str = Form("")):
    uni = wuni.get_active()
    rows = uni.get("rows", []) if uni else []
    tickers = [r.get("factset_ticker") for r in rows if r.get("factset_ticker")]
    if not tickers:
        # Still produce a usable single-ticker example so the download never 500s.
        tickers = ["0001-HK"]
    want_zip = _truthy(as_zip) or (len(tickers) > wtpl.BATCH_SIZE)
    if want_zip and len(tickers) > wtpl.BATCH_SIZE:
        files = wtpl.build_weekly_templates_batched(tickers)
        data = wtpl.zip_templates(files)
        return Response(content=data, media_type="application/zip",
                        headers={"Content-Disposition":
                                 "attachment; filename=weekly_templates.zip"})
    data = wtpl.build_weekly_template(tickers)
    return Response(content=data, media_type=_XLSX_CT,
                    headers={"Content-Disposition":
                             "attachment; filename=weekly_template.xlsx"})


# ---------------------------------------------------------------------------
# (c) Populated-data upload
# ---------------------------------------------------------------------------
@router.post("/weekly/data/upload")
async def weekly_data_upload(file: UploadFile = File(...)):
    content = await file.read()
    parsed = wing.parse_weekly_workbook(content, file.filename or "")
    if parsed.get("error") and not parsed.get("tickers") and not parsed.get("hsi"):
        return RedirectResponse(f"/weekly?err={quote(str(parsed['error'])[:300])}",
                                status_code=303)
    wsnap.save_snapshot(parsed, name=(file.filename or "weekly data"), make_active=True)
    n = len((parsed.get("tickers") or {}))
    hsi = "HSI loaded" if parsed.get("hsi") else "no HSI sheet"
    asof = parsed.get("asof") or "unknown"
    warn = f" {parsed['error']}" if parsed.get("error") else ""
    msg = f"Ingested {n} tickers ({hsi}); as-of {asof}.{warn}"
    return RedirectResponse(f"/weekly?msg={quote(msg[:400])}", status_code=303)


@router.post("/weekly/data/activate")
def weekly_data_activate(sid: int = Form(...)):
    wsnap.set_active(sid)
    return RedirectResponse("/weekly", status_code=303)


# ---------------------------------------------------------------------------
# (d) Generate note + view / export
# ---------------------------------------------------------------------------
def _build_note(provider_name: str = "", with_news: Optional[bool] = None) -> Dict[str, Any]:
    """Compute metrics from the active snapshot, resolve provider, generate the
    note. Never raises. Returns the note dict (exporter-shaped)."""
    snap = wsnap.get_active()
    data = snap.get("data", {}) if snap else {}
    metrics = wmetrics.compute_weekly_metrics(data or {})
    provider = _resolve_note_provider(provider_name)
    fallbacks = build_fallback_providers(getattr(provider, "name", "")) if provider else []
    if with_news is None:
        with_news = is_web_capable(provider)
    note = wnote.generate_weekly_note(
        provider, metrics, asof=metrics.get("asof"),
        with_news=bool(with_news), fallback_providers=fallbacks,
    )
    note["_metrics"] = metrics
    return note


@router.post("/weekly/note", response_class=HTMLResponse)
def weekly_note_generate(request: Request, provider: str = Form(""),
                         with_news: str = Form("")):
    snap = wsnap.get_active()
    if not snap or not (snap.get("data") or {}).get("tickers"):
        return HTMLResponse("<div class='note error'>Upload a populated weekly "
                            "workbook first (no active data snapshot).</div>")
    wn = _truthy(with_news) if with_news != "" else None
    note = _build_note(provider, wn)
    metrics = note.pop("_metrics", {})
    # Persist to dated history.
    try:
        wnotes.save_note(note.get("asof"), note.get("provider"), metrics,
                         note.get("markdown") or "")
    except Exception:  # noqa: BLE001 — persistence must not break the response
        pass
    import markdown as _md
    body_html = _md.markdown(note.get("markdown") or "", extensions=["tables"])
    return templates.TemplateResponse(
        request, "partials/weekly_note.html",
        {"request": request, "note": note, "body_html": body_html},
    )


@router.get("/weekly/note/{note_id}/export")
def weekly_note_export(note_id: int, fmt: str = "md"):
    rec = wnotes.get_note(note_id)
    if not rec:
        return Response("Note not found", status_code=404)
    note = {
        "markdown": rec.get("markdown") or "",
        "candidates": [],
        "asof": rec.get("asof"),
        "provider": rec.get("provider"),
        "title": wnote.TITLE,
        "kind": "weekly",
    }
    try:
        data, ct, fname = exporters.export(note, fmt)
    except ValueError:
        return Response("Unknown format", status_code=400)
    return Response(content=data, media_type=ct,
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@router.get("/weekly/note/{note_id}", response_class=HTMLResponse)
def weekly_note_view(request: Request, note_id: int):
    rec = wnotes.get_note(note_id)
    if not rec:
        return RedirectResponse("/weekly?err=Note+not+found", status_code=303)
    note = {
        "markdown": rec.get("markdown") or "",
        "asof": rec.get("asof"),
        "provider": rec.get("provider"),
        "title": wnote.TITLE, "kind": "weekly",
    }
    import markdown as _md
    body_html = _md.markdown(note["markdown"], extensions=["tables"])
    return templates.TemplateResponse(
        request, "partials/weekly_note.html",
        {"request": request, "note": note, "body_html": body_html, "note_id": note_id},
    )
