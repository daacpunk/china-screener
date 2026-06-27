"""Phase D weekly note: degrades with no provider (tables only); web catalyst
section fires only on a web-capable provider; export round-trips; store history."""
import numpy as np
import pandas as pd

from app import exporters
from app.llm.base import LLMProvider
from app.weekly import metrics as M
from app.weekly import note as N
from app.weekly import note_store as wns


class FakeAnthropic(LLMProvider):
    """Non-web-capable fake provider returning canned prose."""
    name = "fake"

    def __init__(self, *a, **k):
        super().__init__("fake-key", "fake-model")

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        return "Canned section prose grounded in the provided figures."


class FakePerplexity(FakeAnthropic):
    """Web-capable fake (name=='perplexity')."""
    name = "perplexity"


def _metrics():
    dates = pd.bdate_range("2026-01-01", periods=130).strftime("%Y-%m-%d").tolist()
    def recs(p, v):
        return [{"date": d, "close": float(x), "volume": float(y)}
                for d, x, y in zip(dates, p, v)]
    up = list(np.linspace(100, 118, 125)) + [119, 121, 123, 126, 130]
    dn = list(np.linspace(100, 95, 130))
    snap = {
        "asof": "2026-06-26", "stale": False, "n_stale": 1, "partial": [],
        "tickers": {"AAA-HK": recs(up, [1e6] * 125 + [3e6, 1e6, 1e6, 1e6, 1e6]),
                    "BBB-HK": recs(dn, [1e6] * 130)},
        "hsi": [{"date": d, "close": float(c)}
                for d, c in zip(dates, np.linspace(20000, 21000, 130))],
    }
    return M.compute_weekly_metrics(snap)


def test_no_provider_degrades_to_tables():
    m = _metrics()
    note = N.generate_weekly_note(None, m, with_news=True)
    assert note["provider"] is None
    assert note["error"]  # "set a key" hint
    md = note["markdown"]
    assert md.startswith("# Weekly Quant One-Pager")
    # raw metric tables are present even without a key
    assert "Movers & shakers" in md
    assert "HSI benchmark (computed)" in md
    # no fabricated prose sections
    assert "Data observations" not in md


def test_web_capable_fires_all_three_sections():
    m = _metrics()
    note = N.generate_weekly_note(FakePerplexity(), m, with_news=True)
    md = note["markdown"]
    assert "## Data observations" in md
    assert "## Catalysts (web)" in md
    assert "## HSI macro view" in md
    assert "## Computed metrics" in md  # deterministic tables always appended
    assert note["notice"] == ""  # web-capable -> no notice


def test_non_web_provider_skips_catalysts_with_notice():
    m = _metrics()
    note = N.generate_weekly_note(FakeAnthropic(), m, with_news=True)
    md = note["markdown"]
    assert "## Data observations" in md
    assert "## Catalysts (web)" not in md  # no web -> no catalyst section
    assert note["notice"]  # soft notice explaining why


def test_catalyst_names_cover_top_and_bottom():
    m = _metrics()
    # gainer AAA and loser BBB should be in the catalyst set
    assert "AAA-HK" in m["catalyst_names"]
    assert "BBB-HK" in m["catalyst_names"]


def test_export_round_trip_all_formats():
    m = _metrics()
    note = N.generate_weekly_note(FakePerplexity(), m, with_news=True)
    for fmt in ("md", "html", "docx", "pdf"):
        data, ct, fname = exporters.export(note, fmt)
        assert isinstance(data, (bytes, bytearray)) and len(data) > 50
        assert fname.startswith("weekly_note_")
    # the weekly title appears in the HTML/MD outputs
    md_bytes, _, _ = exporters.export(note, "md")
    assert b"Weekly Quant One-Pager" in md_bytes


def test_note_store_round_trip(temp_db):
    m = _metrics()
    note = N.generate_weekly_note(FakePerplexity(), m, with_news=True)
    nid = wns.save_note(note["asof"], note["provider"], m, note["markdown"], db_path=temp_db)
    got = wns.get_note(nid, db_path=temp_db)
    assert got["asof"] == "2026-06-26"
    assert got["provider"] == "perplexity"
    assert got["markdown"] == note["markdown"]
    # metrics hydrated back from JSON
    assert got["metrics"]["meta"]["n_tickers"] == 2
    lst = wns.list_notes(db_path=temp_db)
    assert any(r["id"] == nid for r in lst)


def test_generate_never_raises_on_empty_metrics():
    note = N.generate_weekly_note(None, {}, with_news=False)
    assert note["markdown"].startswith("# Weekly Quant One-Pager")


class _BoomProvider(FakePerplexity):
    def complete(self, prompt, **opts):
        raise RuntimeError("provider exploded")


def test_provider_errors_are_captured_not_raised():
    m = _metrics()
    note = N.generate_weekly_note(_BoomProvider(), m, with_news=True)
    # errors captured in the error field; deterministic tables still present
    assert note["error"]
    assert "## Computed metrics" in note["markdown"]
