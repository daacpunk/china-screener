"""Tab 1 — Universe Manager."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

import pandas as pd

from .. import data_ingest as di
from .. import settings_store as ss
from .common import assemble_active_universe, base_ctx, templates

router = APIRouter()


def _universe_summary(db_path=None):
    df = assemble_active_universe(db_path)
    screenable = df[~df.get("below_floor", False).astype(bool)] if not df.empty else df
    below = df[df.get("below_floor", False).astype(bool)] if not df.empty else df
    sector_breakdown = {}
    if not screenable.empty and "sector" in screenable.columns:
        sector_breakdown = screenable.groupby("sector")["ticker"].count().to_dict()
    return {
        "total": int(len(df)),
        "screenable": int(len(screenable)),
        "below_floor": int(len(below)),
        "below_rows": below.where(pd.notna(below), None).to_dict("records") if not below.empty else [],
        "sector_breakdown": sector_breakdown,
        "rows": screenable.where(pd.notna(screenable), None).to_dict("records") if not screenable.empty else [],
    }


@router.get("/universe", response_class=HTMLResponse)
def universe_page(request: Request):
    params = ss.get_screen_params()
    ctx = base_ctx(
        request, "universe",
        summary=_universe_summary(),
        versions=ss.list_universes(),
        active_universe=ss.get_active_universe(),
        adv_floor=params.get("adv_floor", 10_000_000),
    )
    return templates.TemplateResponse(request, "universe.html", ctx)


@router.post("/universe/upload")
async def universe_upload(file: UploadFile = File(...), note: str = Form("")):
    content = await file.read()
    df, report = di.parse_universe(content, file.filename)
    params = ss.get_screen_params()
    floor = float(params.get("adv_floor", 10_000_000))
    df["below_floor"] = pd.to_numeric(df.get("adv_usd_20d"), errors="coerce").fillna(0) < floor
    ss.add_universe(df.to_csv(index=False), filename=file.filename or "upload.csv",
                    note=note, make_active=True)
    return RedirectResponse("/universe", status_code=303)


@router.post("/universe/activate")
def universe_activate(uid: int = Form(...)):
    ss.set_active_universe(uid)
    return RedirectResponse("/universe", status_code=303)


@router.post("/universe/manual")
def universe_manual(tickers: str = Form(...), sector: str = Form(""), sub_industry: str = Form("")):
    active = ss.get_active_universe()
    if not active:
        # create an empty active universe to attach manual names to
        uid = ss.add_universe("ticker,name,sector,sub_industry,index_weight,adv_usd_20d,below_floor\n",
                              filename="manual.csv", note="manual base", make_active=True)
        active = ss.get_active_universe()
    rows = []
    existing = di.csv_to_df(active.get("manual_csv") or "")
    if not existing.empty:
        rows = existing.to_dict("records")
    for raw in tickers.replace("\n", ",").split(","):
        t = raw.strip()
        if not t:
            continue
        rows.append({"ticker": t, "name": t, "sector": sector or "Manual",
                     "sub_industry": sub_industry or "Manual", "index_weight": None,
                     "adv_usd_20d": None, "below_floor": False})
    man_df = pd.DataFrame(rows).drop_duplicates(subset=["ticker"])
    ss.update_universe_manual(active["id"], man_df.to_csv(index=False))
    return RedirectResponse("/universe", status_code=303)


@router.post("/universe/floor")
def universe_floor(adv_floor: float = Form(...)):
    params = ss.get_screen_params()
    params["adv_floor"] = adv_floor
    ss.set_screen_params(params)
    return RedirectResponse("/universe", status_code=303)
