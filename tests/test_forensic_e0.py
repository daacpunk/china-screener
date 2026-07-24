"""Phase E0 — Forensic Check scaffold: nav tab, landing route, store shell.

Scope is intentionally narrow (E0 is scaffold only): page renders, TABS wiring,
store round-trip, and importability of the deferred stub modules. No scoring,
PDF, or template logic is exercised — that lands in later steps.
"""
import importlib

from fastapi.testclient import TestClient

from app.main import app
from app.web.common import TABS

client = TestClient(app)


def test_forensic_page_renders(temp_db):
    r = client.get("/forensic")
    assert r.status_code == 200
    assert "Forensic Check" in r.text


def test_tabs_contains_forensic_and_settings(temp_db):
    ids = [t["id"] for t in TABS]
    assert "forensic" in ids
    assert "settings" in ids
    # Forensic sits after Weekly and before Settings.
    assert ids.index("weekly") < ids.index("forensic") < ids.index("settings")
    # Settings renumbered to 8.
    settings = next(t for t in TABS if t["id"] == "settings")
    assert settings["n"] == 8


def test_store_round_trip(temp_db):
    from app.forensic import store as fstore

    fstore.init(temp_db)
    rid = fstore.save_run(
        mode="ipo",
        company_name="Example Biotech Ltd",
        ticker="1234-HK",
        sector="Healthcare",
        listing_chapter="18A",
        profile="pre_revenue",
        composite_score=62.5,
        letter_rating="C",
        markdown="# Forensic note\n\nBody.",
        metrics={"cash_runway_months": 18},
        source_filenames=["prospectus.pdf"],
        status="ok",
        db_path=temp_db,
    )
    assert isinstance(rid, int) and rid > 0

    runs = fstore.list_runs(limit=50, db_path=temp_db)
    assert any(r["id"] == rid for r in runs)
    row = next(r for r in runs if r["id"] == rid)
    assert row["company_name"] == "Example Biotech Ltd"
    assert row["mode"] == "ipo"
    assert row["letter_rating"] == "C"

    got = fstore.get_run(rid, db_path=temp_db)
    assert got is not None
    assert got["ticker"] == "1234-HK"
    assert got["profile"] == "pre_revenue"
    assert got["composite_score"] == 62.5
    assert got["metrics"] == {"cash_runway_months": 18}
    assert got["source_filenames"] == '["prospectus.pdf"]'

    # Missing run returns None (not raise).
    assert fstore.get_run(999999, db_path=temp_db) is None


def test_run_detail_route_missing_redirects(temp_db):
    # Unknown run id -> friendly redirect back to landing (not a 500).
    r = client.get("/forensic/run/999999", follow_redirects=False)
    assert r.status_code == 303
    assert "/forensic" in r.headers.get("location", "")


def test_stub_modules_import(temp_db):
    import app.forensic  # noqa: F401

    for mod in ("ingest", "extract", "template_gen", "rubric", "score", "note", "store"):
        importlib.import_module(f"app.forensic.{mod}")
