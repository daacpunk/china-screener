"""Tab 4 — Results Data: the screen results table, filters, staleness, export.

AI synthesis and the research-note generator live on the Analysis tab
(routes_analysis.py); both run the same active screen via common.run_active_screen.
"""
from __future__ import annotations

import io

import pandas as pd
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from .. import screen_engine as se
from .. import settings_store as ss
from .common import base_ctx, df_to_records, run_active_screen, templates

router = APIRouter()

# In-memory sidebar synthesis cache keyed by active snapshot id, shared with the
# Analysis page. Invalidated on an explicit Run Screen so a fresh run recomputes.
_SIDEBAR_CACHE: dict = {}


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
