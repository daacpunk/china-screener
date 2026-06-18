"""FastAPI application entrypoint.

$PORT-aware via the Procfile/uvicorn command. Mounts static, templates, and the
five tab routers. Initializes the SQLite schema and seeds demo data on first run.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db as dbmod
from . import demo as demo_mod
from .web import common
from .web.routes_data import router as data_router
from .web.routes_formula import router as formula_router
from .web.routes_results import router as results_router
from .web.routes_settings import router as settings_router
from .web.routes_universe import router as universe_router

BASE = Path(__file__).resolve().parent

app = FastAPI(title="MSCI China Reversion/Fade Screener")

app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.on_event("startup")
def _startup():
    dbmod.init_db()
    demo_mod.maybe_seed_on_startup()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    ctx = common.base_ctx(request, "home")
    return common.templates.TemplateResponse(request, "home.html", ctx)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


app.include_router(universe_router)
app.include_router(formula_router)
app.include_router(data_router)
app.include_router(results_router)
app.include_router(settings_router)
