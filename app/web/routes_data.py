"""Tab 3 — Data Upload & Indicator Engine."""
from __future__ import annotations

import json

import pandas as pd
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import data_ingest as di
from .. import indicators as ind
from .. import settings_store as ss
from .common import active_prices, base_ctx, run_active_screen, templates

router = APIRouter()


def _snapshot_indicator_preview(db_path=None):
    """Compute latest-bar indicators per ticker for the active snapshot."""
    prices = active_prices(db_path)
    if prices.empty:
        return []
    params = ss.get_screen_params(db_path)
    out = []
    for tkr, g in prices.groupby("ticker"):
        g = g.sort_values("date")
        if g["close"].notna().sum() < 30:
            out.append({"ticker": tkr, "rsi": None, "macd_state": "n/a",
                        "rsi_signal": "Unknown", "combined_signal": "Unknown", "bars": int(len(g))})
            continue
        enr = ind.compute_indicators_for_series(
            g, rsi_length=params["rsi_length"], macd_fast=params["macd_fast"],
            macd_slow=params["macd_slow"], macd_signal=params["macd_signal"],
            sma_length=params["sma_length"])
        last = enr.iloc[-1]
        rv = float(last["rsi"]) if pd.notna(last["rsi"]) else None
        mv = float(last["macd"]) if pd.notna(last["macd"]) else float("nan")
        sv = float(last["macd_signal"]) if pd.notna(last["macd_signal"]) else float("nan")
        out.append({
            "ticker": tkr, "rsi": rv,
            "rsi_signal": ind.rsi_signal(rv if rv is not None else float("nan"),
                                         params["rsi_oversold"], params["rsi_overbought"]),
            "macd_state": ind.macd_state(mv, sv),
            "combined_signal": ind.combined_signal(rv if rv is not None else float("nan"), mv, sv,
                                                   params["rsi_oversold"], params["rsi_overbought"]),
            "bars": int(g["close"].notna().sum()),
        })
    return out


@router.get("/data", response_class=HTMLResponse)
def data_page(request: Request):
    snap = ss.get_active_snapshot()
    quality = json.loads(snap["quality_json"]) if snap and snap.get("quality_json") else None
    ctx = base_ctx(request, "data", snapshot=snap, snapshots=ss.list_snapshots(),
                   quality=quality, indicator_backend=ind.INDICATOR_BACKEND,
                   previews=_snapshot_indicator_preview())
    return templates.TemplateResponse(request, "data.html", ctx)


@router.post("/data/upload")
async def data_upload(file: UploadFile = File(...), note: str = Form("")):
    from urllib.parse import quote
    content = await file.read()
    try:
        tidy, report = di.parse_prices(content, file.filename)
    except Exception as e:  # noqa: BLE001 — never 500 on a bad upload
        msg = f"Could not parse the price file: {e}"
        return RedirectResponse(f"/data?err={quote(msg[:300])}", status_code=303)
    if tidy is None or tidy.empty:
        msg = ("No price rows were read from the file. If this is a spill workbook, "
               "make sure you ran the ActivateSpills macro so the formulas filled "
               "in, and that each ticker sheet has close values.")
        return RedirectResponse(f"/data?err={quote(msg[:300])}", status_code=303)
    ss.add_snapshot(tidy.to_csv(index=False), quality_json=json.dumps(report),
                    filename=file.filename or "prices.csv", note=note, make_active=True)
    n = int(report.get("n_tickers", 0))
    return RedirectResponse(f"/data?msg={quote(f'Loaded {n} tickers, {len(tidy)} rows.')}", status_code=303)


@router.post("/data/activate")
def data_activate(sid: int = Form(...)):
    ss.set_active_snapshot(sid)
    return RedirectResponse("/data", status_code=303)


@router.post("/data/run", response_class=HTMLResponse)
def data_run(request: Request):
    res = run_active_screen()
    if res.get("_empty"):
        return HTMLResponse(
            "<div class='note error'>No active universe or price snapshot. "
            "Load sample/demo data in Settings, or upload data above.</div>")
    # Invalidate the cached Results sidebar synthesis for this snapshot so it
    # is regenerated on the next Results load (an explicit Run Screen).
    from .routes_results import _SIDEBAR_CACHE
    snap = ss.get_active_snapshot()
    if snap:
        _SIDEBAR_CACHE.pop(snap["id"], None)
    n_os = len(res["oversold"]); n_ob = len(res["overbought"])
    return HTMLResponse(
        f"<div class='note ok'>Screen complete: <b>{n_os}</b> oversold-reversion longs and "
        f"<b>{n_ob}</b> overbought-fade shorts. "
        f"<a href='/results?run=1'>View Results &rarr;</a></div>")
