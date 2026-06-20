"""CHANGE 3 — Results Data + Analysis pages render 200 on an empty DB and with a
screen loaded; the note-export endpoint returns the right content-type/bytes."""
from fastapi.testclient import TestClient

from app import notes_store as ns
from app.main import app

client = TestClient(app)


def test_results_data_renders_empty(temp_db):
    r = client.get("/results")
    assert r.status_code == 200
    assert "Results Data" in r.text


def test_analysis_renders_empty(temp_db):
    r = client.get("/analysis")
    assert r.status_code == 200
    assert "Analysis" in r.text


def test_nav_order_results_then_analysis(temp_db):
    r = client.get("/")
    assert r.status_code == 200
    assert r.text.index("Results Data") < r.text.index("Analysis")


def test_legacy_note_routes_still_work(temp_db):
    # old /results/notes path must not 404 (back-compat alias)
    assert client.get("/results/notes").status_code == 200
    assert client.get("/analysis/notes").status_code == 200


def test_note_export_endpoint_content_types(temp_db):
    nid = ns.save_note("2026-06-20", "anthropic",
                       [{"ticker": "AAA", "name": "Alpha", "side": "long",
                         "sector": "Tech", "rank_z": -2.0, "rsi": 25.0,
                         "reversion_score": 0.7, "dislocation_type": "IDIOSYNCRATIC"}],
                       "# Note\n\nBody.", db_path=temp_db)
    cases = {
        "md": "text/markdown",
        "html": "text/html",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }
    for fmt, ctype in cases.items():
        r = client.get(f"/analysis/note/export?id={nid}&fmt={fmt}")
        assert r.status_code == 200, fmt
        assert ctype in r.headers["content-type"], fmt
        assert len(r.content) > 50, fmt
        assert "attachment" in r.headers["content-disposition"]


def test_note_export_missing_returns_404(temp_db):
    assert client.get("/analysis/note/export?id=999999&fmt=md").status_code == 404
