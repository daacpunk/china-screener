"""Tab 7 — Forensic Check (Phase E): a GMT-Research-style forensic accounting
screen for HKEX IPOs and listed names.

E0 = scaffold only. This module renders a landing page and wires up the run-
history links so later steps (Excel template, scoring engine, PDF ingest) have a
place to land. No scoring / PDF / template logic yet — see app/forensic/ stubs.
"""
from __future__ import annotations

from typing import Any, Dict
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..forensic import store as fstore
from .common import base_ctx, templates

router = APIRouter()

# Ensure the forensic_runs table exists at import time (same spirit as weekly,
# whose stores self-init on first use). init() is idempotent and never raises.
fstore.init()

# The three input modes that will be available once the pipeline is built.
MODES = [
    {"id": "ipo", "label": "IPO / PHIP",
     "desc": "Official HKEX prospectus or PHIP (PDF) — pre-listing diligence."},
    {"id": "listed_pdf", "label": "Listed (PDF)",
     "desc": "Annual or interim report PDF — ongoing coverage / risk monitor."},
    {"id": "listed_excel", "label": "Listed (Excel)",
     "desc": "Standardized FactSet Excel template the app generates, you "
             "populate, and re-upload."},
]

# Sequential build status shown on the landing page.
PIPELINE = [
    {"step": "E0", "label": "Scaffold — nav tab, route, store shell, landing", "done": True},
    {"step": "E1", "label": "Excel forensic template generation", "done": False},
    {"step": "E2", "label": "Rubric + weight profiles + kill-switch", "done": False},
    {"step": "E3", "label": "Excel parse → CanonicalFacts", "done": False},
    {"step": "E4", "label": "PDF ingest + LLM extraction", "done": False},
    {"step": "E5", "label": "Scoring engine (composite + letter)", "done": False},
    {"step": "E6", "label": "One-pager note + MD/DOCX/PDF export", "done": False},
    {"step": "E7", "label": "Worked example on a user-uploaded prospectus", "done": False},
]


def _forensic_ctx(request: Request, **extra) -> Dict[str, Any]:
    ctx = base_ctx(
        request, "forensic",
        modes=MODES,
        pipeline=PIPELINE,
        runs=fstore.list_runs(limit=50),
    )
    ctx.update(extra)
    return ctx


@router.get("/forensic", response_class=HTMLResponse)
def forensic_page(request: Request):
    return templates.TemplateResponse(request, "forensic.html", _forensic_ctx(request))


@router.get("/forensic/run/{run_id}", response_class=HTMLResponse)
def forensic_run(request: Request, run_id: int):
    """History-link stub. Loads a run if present; otherwise redirects back to the
    landing page with an error flash. Full run detail lands in a later step."""
    run = fstore.get_run(run_id)
    if not run:
        return RedirectResponse(
            f"/forensic?err={quote('Run #%d not found.' % run_id)}", status_code=303
        )
    # E0: no dedicated detail template yet — re-render the landing page with the
    # loaded run in context so the link resolves. Detail view arrives later.
    return templates.TemplateResponse(
        request, "forensic.html", _forensic_ctx(request, active_run=run)
    )
