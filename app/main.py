"""FastAPI application entrypoint.

$PORT-aware via the Procfile/uvicorn command. Mounts static, templates, and the
tab routers. Initializes the SQLite schema. A fresh deploy starts EMPTY — there
is no demo/sample seeding. The most recently uploaded MSCI universe (stored on
the /data volume) is the active default and is auto-loaded on startup, surviving
restarts and redeploys.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db as dbmod
from . import settings_store as ss
from .web import common
from .web.routes_analysis import router as analysis_router
from .web.routes_data import router as data_router
from .web.routes_forensic import router as forensic_router
from .web.routes_formula import router as formula_router
from .web.routes_results import router as results_router
from .web.routes_settings import router as settings_router
from .web.routes_universe import router as universe_router
from .web.routes_weekly import router as weekly_router

BASE = Path(__file__).resolve().parent

app = FastAPI(title="MSCI China Reversion/Fade Screener")

app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.on_event("startup")
def _startup():
    # A fresh deploy starts empty with clean empty states — no demo seeding.
    dbmod.init_db()
    # Persist the latest uploaded universe as the active default across restarts:
    # if rows exist but none is flagged active (e.g. an older DB), promote newest.
    ss.ensure_active_universe()


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
app.include_router(analysis_router)
app.include_router(weekly_router)
app.include_router(forensic_router)
app.include_router(settings_router)
