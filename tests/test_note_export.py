"""CHANGE 3/4 — Analysis page renders, and note export to md/html/docx/pdf
produces non-empty bytes with the right content-type. Exports must also work
when the note has no markdown body (only the candidate table)."""
from app import exporters
from app import notes_store as ns


_CANDIDATES = [
    {"ticker": "AAA", "name": "Alpha Co", "side": "long", "sector": "Tech",
     "rank_z": -2.31, "peer_relative_z": -1.8, "rsi": 22.5,
     "reversion_score": 0.812, "dislocation_type": "IDIOSYNCRATIC",
     "verdict": "MECHANICAL_DISLOCATION"},
    {"ticker": "ZZZ", "name": "Zeta Co", "side": "short", "sector": "Energy",
     "rank_z": 2.10, "peer_relative_z": 1.6, "rsi": 78.0,
     "fade_score": 0.640, "dislocation_type": "SECTOR",
     "verdict": "BROKEN_STORY"},
]

_MD = ("# Research Note\n\n## Alpha Co (AAA)\n\n"
       "- **Recommendation:** LONG\n- **Conviction:** Med\n\n"
       "Mechanical dislocation; reversion reasonable.\n")


def _save_note(db_path, markdown=_MD):
    return ns.save_note("2026-06-20", "anthropic", _CANDIDATES, markdown, db_path=db_path)


def test_export_all_formats_nonempty(temp_db):
    note = ns.get_note(_save_note(temp_db), db_path=temp_db)
    for fmt, ctype_part in (("md", "markdown"), ("html", "html"),
                            ("docx", "wordprocessingml"), ("pdf", "pdf")):
        data, ctype, fname = exporters.export(note, fmt)
        assert data, f"{fmt} export must be non-empty"
        assert len(data) > 50
        assert ctype_part in ctype
        assert fname.endswith(f".{fmt}")


def test_pdf_magic_bytes(temp_db):
    note = ns.get_note(_save_note(temp_db), db_path=temp_db)
    data, _, _ = exporters.export(note, "pdf")
    assert data[:4] == b"%PDF"


def test_docx_is_zip(temp_db):
    note = ns.get_note(_save_note(temp_db), db_path=temp_db)
    data, _, _ = exporters.export(note, "docx")
    assert data[:2] == b"PK"  # docx is a zip container


def test_export_handles_empty_markdown(temp_db):
    """A note generated without an AI key has markdown='' — export the candidate
    table gracefully across every format."""
    note = ns.get_note(_save_note(temp_db, markdown=""), db_path=temp_db)
    for fmt in ("md", "html", "docx", "pdf"):
        data, _, _ = exporters.export(note, fmt)
        assert data and len(data) > 50
    # the ticker should still appear in the text formats
    md_text = exporters.to_markdown(note)
    assert "AAA" in md_text
    html = exporters.to_html(note)
    assert "AAA" in html


def test_export_unknown_format_raises(temp_db):
    note = ns.get_note(_save_note(temp_db), db_path=temp_db)
    try:
        exporters.export(note, "xml")
    except ValueError:
        return
    raise AssertionError("unknown format should raise ValueError")
