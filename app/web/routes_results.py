"""Tab 4 — Results + optional key-gated LLM analysis."""
from __future__ import annotations

import io

import pandas as pd
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from .. import settings_store as ss
from ..llm import analysis as la
from ..llm.registry import build_provider
from .common import base_ctx, df_to_records, run_active_screen, templates

router = APIRouter()


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
    if hide_event:
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
    ctx = base_ctx(
        request, "results", empty=empty,
        oversold=df_to_records(oversold), overbought=df_to_records(overbought),
        master=df_to_records(master), sectors=sectors, subs=subs,
        skipped=df_to_records(res.get("skipped")), filters=q,
        providers=providers, any_key=any_key,
        params=ss.get_screen_params(),
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
