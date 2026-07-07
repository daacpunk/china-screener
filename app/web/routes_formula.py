"""Tab 2 — FactSet Price-Series Formula Generator."""
from __future__ import annotations

import markdown as md
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from .. import formula_gen as fg
from .. import settings_store as ss
from .common import assemble_active_universe, base_ctx, templates

router = APIRouter()


def _active_dict():
    d = ss.get_active_dictionary()
    return d


@router.get("/formula", response_class=HTMLResponse)
def formula_page(request: Request):
    d = _active_dict()
    tickers = []
    uni = assemble_active_universe()
    if not uni.empty:
        tickers = uni["ticker"].tolist()
    metric_keys = list(d["data"].get("formulas", {}).keys()) if d else []
    md_html = md.markdown(d["md_text"], extensions=["tables"]) if d and d.get("md_text") else ""
    auto = fg.autodetect_metrics(d["data"]) if d else {"price_metric": "", "volume_metric": ""}
    try:
        auto_depth = fg.min_required_bars(ss.get_screen_params())
    except Exception:
        auto_depth = fg.min_required_bars(None)
    # sample preview
    preview = None
    if d and metric_keys and tickers:
        preview = fg.generate_formula(tickers[0], metric_keys[0], d["data"],
                                      start="0D", end="-150D", freq="D")
    default_batch = 75
    n = len(tickers)
    n_files = (n + default_batch - 1) // default_batch if n else 0
    ctx = base_ctx(request, "formula", active_dict=d, metric_keys=metric_keys,
                   tickers=tickers, md_html=md_html, preview=preview,
                   default_price_metric=auto["price_metric"],
                   default_volume_metric=auto["volume_metric"],
                   auto_depth=auto_depth, n_tickers=len(tickers),
                   default_batch=default_batch, n_files=n_files)
    return templates.TemplateResponse(request, "formula.html", ctx)


def _resolve_metrics(d: dict, price_metric: str, volume_metric: str) -> tuple[str, str]:
    """Use submitted metric keys if valid, else auto-detect from the dict."""
    keys = set((d["data"].get("formulas", {}) if d else {}).keys())
    auto = fg.autodetect_metrics(d["data"]) if d else {"price_metric": "price", "volume_metric": "volume"}
    pm = price_metric if price_metric in keys else auto["price_metric"]
    vm = volume_metric if volume_metric in keys else auto["volume_metric"]
    return pm or "price", vm or "volume"


@router.post("/formula/preview", response_class=HTMLResponse)
def formula_preview(request: Request, ticker: str = Form(...), metric_key: str = Form(...),
                    start: str = Form("0D"), end: str = Form("-150D"), freq: str = Form("D"),
                    price_metric: str = Form(""), volume_metric: str = Form("")):
    d = _active_dict()
    if not d:
        return HTMLResponse("<div class='note error'>No active dictionary. Upload one in Settings.</div>")
    pm, vm = _resolve_metrics(d, price_metric, volume_metric)
    formula = fg.generate_formula(ticker, metric_key, d["data"], start=start, end=end, freq=freq)
    a = fg.method_a_timeseries_formulas(ticker, d["data"], start=start, end=end, freq=freq,
                                        price_metric=pm, volume_metric=vm)
    b = fg.method_b_offset_grid(d["data"], lookback=5, price_metric=pm, volume_metric=vm)
    return templates.TemplateResponse(request, "partials/formula_preview.html",
                                      {"formula": formula, "method_a": a, "method_b": b[:5]})


@router.post("/formula/download")
def formula_download(method: str = Form("A"), lookback: int = Form(0),
                     start: str = Form("0D"), end: str = Form("-150D"),
                     freq: str = Form("D"), layout: str = Form("spill"),
                     price_metric: str = Form(""), volume_metric: str = Form(""),
                     include_date: str = Form(""), include_event: str = Form(""),
                     include_name: str = Form("1"), include_events: str = Form("1"),
                     batch_size: int = Form(75), as_zip: str = Form("")):
    d = _active_dict()
    if not d:
        return Response("No active dictionary", status_code=400)
    pm, vm = _resolve_metrics(d, price_metric, volume_metric)
    # Efficient default: size the pull to the MINIMUM contiguous depth the screen
    # needs (from current params) when lookback isn't explicitly set (<=0).
    if not lookback or lookback <= 0:
        try:
            params = ss.get_screen_params()
        except Exception:
            params = None
        lookback = fg.min_required_bars(params)
    inc_date = str(include_date).lower() in ("1", "true", "on", "yes")
    inc_event = str(include_event).lower() in ("1", "true", "on", "yes")
    # Company name defaults ON (backward-compatible extra column); only an
    # explicit off value ('0'/'false'/'off'/'no') disables it.
    inc_name = str(include_name).strip().lower() not in ("0", "false", "off", "no", "")
    # Event dates (earnings + ex-dividend) default ON (backward-compatible extra
    # columns); only an explicit off value disables them.
    inc_events = str(include_events).strip().lower() not in ("0", "false", "off", "no", "")
    uni = assemble_active_universe()
    tickers = uni["ticker"].tolist() if not uni.empty else ["BABA-CN"]
    bsize = batch_size if batch_size and batch_size > 0 else 75
    # Default behavior: auto-zip when the universe exceeds the batch size, unless
    # explicitly turned off. Honor an explicit as_zip flag when provided.
    as_zip_raw = str(as_zip).strip().lower()
    if as_zip_raw in ("1", "true", "on", "yes"):
        want_zip = True
    elif as_zip_raw in ("0", "false", "off", "no"):
        want_zip = False
    else:
        want_zip = len(tickers) > bsize

    if want_zip and len(tickers) > bsize:
        files = fg.build_formula_workbooks_batched(
            tickers, d["data"], method=method, lookback=lookback,
            start=start, end=end, freq=freq, layout=layout,
            price_metric=pm, volume_metric=vm, include_date=inc_date,
            include_event=inc_event, include_name=inc_name,
            include_events=inc_events, batch_size=bsize)
        zip_bytes = fg.zip_workbooks(files)
        zname = f"factset_formulas_method_{method}.zip"
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={zname}"},
        )

    data = fg.build_formula_workbook(tickers, d["data"], method=method, lookback=lookback,
                                     start=start, end=end, freq=freq, layout=layout,
                                     price_metric=pm, volume_metric=vm,
                                     include_date=inc_date, include_event=inc_event,
                                     include_name=inc_name, include_events=inc_events)
    fname = f"factset_formulas_method_{method}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )
