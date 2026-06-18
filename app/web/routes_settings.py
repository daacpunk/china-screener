"""Tab 5 — Settings (Admin): dictionary versions, API keys, screen params."""
from __future__ import annotations

import markdown as md
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import demo as demo_mod
from .. import settings_store as ss
from ..llm.models import PROVIDER_MODELS
from ..llm.registry import build_provider
from .common import base_ctx, templates

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    active_dict = ss.get_active_dictionary()
    md_html = md.markdown(active_dict["md_text"], extensions=["tables"]) if active_dict and active_dict.get("md_text") else ""
    section_labels = [
        ("per_name", "Per-name notes"),
        ("portfolio", "Portfolio synthesis"),
        ("sidebar", "Results sidebar explanations"),
        ("news", "News / catalyst classification (best with Perplexity Sonar)"),
    ]
    section_providers = {s: ss.get_section_provider_raw(s) for s in ss.SECTIONS}
    ctx = base_ctx(
        request, "settings",
        dictionaries=ss.list_dictionaries(),
        active_dict=active_dict, md_html=md_html,
        providers=ss.list_provider_configs(),
        provider_models=PROVIDER_MODELS,
        default_provider=ss.get_default_provider(),
        section_labels=section_labels,
        section_providers=section_providers,
        params=ss.get_screen_params(),
        msg=request.query_params.get("msg", ""),
        err=request.query_params.get("err", ""),
    )
    return templates.TemplateResponse(request, "settings.html", ctx)


# ---- 5a dictionary management ----
@router.post("/settings/dictionary")
async def settings_dictionary(json_file: UploadFile = File(...),
                              md_file: UploadFile = File(None), note: str = Form("")):
    try:
        json_text = (await json_file.read()).decode("utf-8")
        md_text = ""
        if md_file is not None and md_file.filename:
            md_text = (await md_file.read()).decode("utf-8")
        result = ss.add_dictionary(json_text, md_text, filename=json_file.filename or "dict.json",
                                   note=note, make_active=True, is_demo=False)
        # A real user upload voids the bundled sample/demo dictionary.
        voided = ss.void_demo_dictionaries()
        diff = result["diff"]
        msg = f"Dictionary v{result['id']} active. Added: {diff['added']} Removed: {diff['removed']}"
        if voided:
            msg += f". Voided {voided} demo dictionary row(s)."
        return RedirectResponse(f"/settings?msg={msg}", status_code=303)
    except ValueError as e:
        return RedirectResponse(f"/settings?err=Dictionary rejected: {e}", status_code=303)


@router.post("/settings/dictionary/activate")
def settings_dict_activate(dict_id: int = Form(...)):
    ss.set_active_dictionary(dict_id)
    return RedirectResponse("/settings", status_code=303)


# ---- 5b API keys ----
@router.post("/settings/apikey")
def settings_apikey(provider: str = Form(...), api_key: str = Form(""),
                    model: str = Form(""), model_custom: str = Form(""),
                    enabled: str = Form("")):
    # "Other (custom)" reveals a free-text input whose value lives in model_custom.
    chosen = model_custom.strip() if model == "__custom__" else model
    ss.set_api_key(provider, api_key, model=chosen or None, enabled=(enabled == "on"))
    return RedirectResponse("/settings?msg=Key saved", status_code=303)


@router.post("/settings/section_provider")
def settings_section_provider(section: str = Form(...), provider: str = Form("")):
    try:
        ss.set_section_provider(section, provider)
    except ValueError as e:
        return RedirectResponse(f"/settings?err={e}", status_code=303)
    return RedirectResponse("/settings?msg=Section AI updated", status_code=303)


@router.post("/settings/default_provider")
def settings_default_provider(provider: str = Form(...)):
    ss.set_default_provider(provider)
    return RedirectResponse("/settings?msg=Default provider set", status_code=303)


@router.post("/settings/test", response_class=HTMLResponse)
def settings_test(request: Request, provider: str = Form(...)):
    key = ss.get_api_key(provider)
    cfg = ss.get_provider_config(provider)
    prov = build_provider(provider, key, cfg["model"])
    if prov is None:
        return HTMLResponse("<span class='note error'>No key configured.</span>")
    result = prov.ping()
    cls = "ok" if result["ok"] else "error"
    return HTMLResponse(f"<span class='note {cls}'>{'OK' if result['ok'] else 'FAIL'}: {result['detail']}</span>")


# ---- 5c screen params ----
@router.post("/settings/params")
async def settings_params(request: Request):
    form = await request.form()
    params = ss.get_screen_params()
    numeric = ["horizon_a_lookback", "horizon_b_start", "horizon_b_end", "vol_window",
               "rsi_length", "rsi_oversold", "rsi_overbought", "macd_fast", "macd_slow",
               "macd_signal", "sma_length", "z_cutoff", "divergence_threshold",
               "event_window_days", "min_bars", "adv_floor", "z_weight_a", "z_weight_b"]
    for k in numeric:
        if k in form and str(form[k]).strip() != "":
            try:
                params[k] = float(form[k]) if ("." in str(form[k]) or k in ("z_cutoff","divergence_threshold","rsi_oversold","rsi_overbought","z_weight_a","z_weight_b","adv_floor")) else int(float(form[k]))
            except Exception:
                pass
    ss.set_screen_params(params)
    return RedirectResponse("/settings?msg=Parameters saved", status_code=303)


@router.post("/settings/params/reset")
def settings_params_reset():
    ss.reset_screen_params()
    return RedirectResponse("/settings?msg=Parameters reset to defaults", status_code=303)


# ---- demo data ----
@router.post("/settings/demo")
def settings_demo():
    summary = demo_mod.load_demo_data()
    return RedirectResponse(f"/settings?msg=Demo data loaded: {summary}", status_code=303)
