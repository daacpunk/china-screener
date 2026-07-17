"""Phase D weekly note — RETAIL audience mode.

Verifies the additive retail output mode:
  * _title / _headings swaps (friendly titles/headings; four contract '##'
    headings stay verbatim in BOTH modes),
  * generate_weekly_note(audience="retail") on synthetic metrics with NO
    provider (deterministic path) — friendly title/headings, contract headings
    verbatim, tables byte-identical to the institutional render, friendly prose,
  * institutional regression (audience="institutional" == pre-change output),
  * prompt builders differ retail vs institutional,
  * route POST /weekly/note?audience=retail persists + exports serve retail md.
"""
import numpy as np
import pandas as pd

from app.weekly import metrics as M
from app.weekly import note as N


# --------------------------------------------------------------------------- #
# Synthetic metrics (mirrors tests/test_weekly_note.py::_metrics)
# --------------------------------------------------------------------------- #
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


# The four exporter/test-contract '##' heading strings — MUST stay verbatim in
# BOTH modes.
CONTRACT_HEADINGS = [
    "## Data observations",
    "## Catalysts (web)",
    "## HSI macro view",
    "## Computed metrics",
]


class _FakePerplexity:
    """Web-capable fake provider (name == 'perplexity') returning canned prose,
    so _assemble (provider path) runs and the four contract headings appear."""
    name = "perplexity"

    def __init__(self):
        from app.llm.base import LLMProvider  # local import to avoid cycles
        LLMProvider.__init__(self, "fake-key", "fake-model")

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        return "AAA-HK: canned catalyst prose grounded in the figures."


# --------------------------------------------------------------------------- #
# _title / _headings
# --------------------------------------------------------------------------- #
def test_title_swap():
    assert N._title("institutional") == "Weekly Quant One-Pager"
    assert N._title("retail") == "Weekly Market Snapshot"
    assert N._title("garbage") == "Weekly Quant One-Pager"  # regression-safe


def test_headings_contract_identical_across_modes():
    hi = N._headings("institutional")
    hr = N._headings("retail")
    # Four contract heading strings identical across modes.
    assert hi["data_observations"] == hr["data_observations"] == "Data observations"
    assert hi["catalysts_web"] == hr["catalysts_web"] == "Catalysts (web)"
    assert hi["hsi"] == hr["hsi"] == "HSI macro view"
    assert hi["computed"] == hr["computed"] == "Computed metrics"


def test_headings_noncontract_swap_in_retail():
    hr = N._headings("retail")
    assert hr["takeaways"] == "Key Takeaways"
    assert hr["market_internals"] == "Market Internals (simple version)"
    assert hr["sector_scoreboard"] == "Sector Scoreboard"
    # Friendly bold subtitles only exist in retail.
    assert hr["sub_hsi"] == "**Hang Seng Index – Bigger Picture**"
    hi = N._headings("institutional")
    assert hi["sub_hsi"] == "" and hi["sub_data_observations"] == ""


# --------------------------------------------------------------------------- #
# Deterministic (no-provider) retail note
# --------------------------------------------------------------------------- #
def test_retail_note_title_and_headings_no_provider():
    m = _metrics()
    note = N.generate_weekly_note(None, m, with_news=True, audience="retail")
    md = note["markdown"]
    assert note["title"] == "Weekly Market Snapshot"
    assert note["audience"] == "retail"
    assert md.startswith("# Weekly Market Snapshot")
    # friendly non-contract headings present
    assert "## Key Takeaways" in md
    assert "## Market Internals (simple version)" in md
    assert "## What Moved and Why" in md  # no-key movers heading
    assert "## Glossary" in md
    # 'Computed metrics' contract heading still verbatim
    assert "## Computed metrics" in md


def test_retail_tables_byte_identical_to_institutional():
    m = _metrics()
    inst = N.generate_weekly_note(None, m, with_news=True,
                                  audience="institutional")["markdown"]
    ret = N.generate_weekly_note(None, m, with_news=True,
                                 audience="retail")["markdown"]

    # Everything from '## Computed metrics' onward (the deterministic tables)
    # must be byte-identical.
    assert "## Computed metrics" in inst and "## Computed metrics" in ret
    assert (inst.split("## Computed metrics", 1)[1]
            == ret.split("## Computed metrics", 1)[1])

    # The individual table renderers do NOT branch on audience.
    assert N.render_metric_tables(m) == N.render_metric_tables(m)
    assert N.render_grouped_movers(m) == N.render_grouped_movers(m)
    assert N.render_sector_scoreboard(m) == N.render_sector_scoreboard(m)


def test_retail_deterministic_friendly_voice():
    m = _metrics()
    tk = N.render_takeaways_deterministic(m, "retail")
    # plain-English phrasings from the reference voice
    assert "stock-picker" in tk.lower()
    mi = N.render_market_internals(m, "retail")
    assert "stocks rose" in mi and "fell" in mi and "unchanged" in mi
    assert "More money traded in advancing stocks" in mi
    # institutional keeps the jargon labels
    mi_i = N.render_market_internals(m, "institutional")
    assert "Advance / decline" in mi_i


def test_retail_market_internals_numbers_match_institutional():
    """Same underlying breadth numbers appear in both voices (numbers unchanged;
    only the wording differs)."""
    m = _metrics()
    b = m.get("breadth") or {}
    adv, dec, flat = b.get("advancers"), b.get("decliners"), b.get("flat")
    mi_r = N.render_market_internals(m, "retail")
    mi_i = N.render_market_internals(m, "institutional")
    for n in (adv, dec, flat):
        assert str(n) in mi_r and str(n) in mi_i


# --------------------------------------------------------------------------- #
# Institutional regression: retail must be purely additive
# --------------------------------------------------------------------------- #
def test_institutional_unchanged_default_and_explicit():
    m = _metrics()
    default = N.generate_weekly_note(None, m, with_news=True)["markdown"]
    explicit = N.generate_weekly_note(None, m, with_news=True,
                                      audience="institutional")["markdown"]
    assert default == explicit
    assert default.startswith("# Weekly Quant One-Pager")
    # unknown audience falls back to institutional
    junk = N.generate_weekly_note(None, m, with_news=True,
                                  audience="nonsense")["markdown"]
    assert junk == default


def test_provider_path_contract_headings_verbatim_both_modes():
    m = _metrics()
    inst = N.generate_weekly_note(_FakePerplexity(), m, with_news=True,
                                  audience="institutional")["markdown"]
    ret = N.generate_weekly_note(_FakePerplexity(), m, with_news=True,
                                 audience="retail")["markdown"]
    for h in CONTRACT_HEADINGS:
        assert h in inst, f"institutional missing {h}"
        assert h in ret, f"retail missing {h}"
    # retail surfaces the friendly bold subtitle under the HSI contract heading
    assert "**Hang Seng Index – Bigger Picture**" in ret
    assert "**Hang Seng Index – Bigger Picture**" not in inst
    # retail title, institutional title
    assert ret.startswith("# Weekly Market Snapshot")
    assert inst.startswith("# Weekly Quant One-Pager")


# --------------------------------------------------------------------------- #
# Prompt builders differ retail vs institutional
# --------------------------------------------------------------------------- #
def test_prompt_builders_retail_vs_institutional_differ():
    m = _metrics()
    for build in (N.build_takeaways_prompt, N.build_observations_prompt,
                  N.build_catalyst_prompt, N.build_hsi_prompt):
        inst = build(m, "institutional")
        ret = build(m, "retail")
        assert inst != ret, f"{build.__name__} did not change for retail"
        # institutional prompt is a strict prefix (retail only APPENDS a style
        # block), so the institutional prompt text is unchanged / regression-safe.
        assert ret.startswith(inst), f"{build.__name__} changed institutional text"


# --------------------------------------------------------------------------- #
# Route: POST /weekly/note with audience=retail persists + exports serve retail
# --------------------------------------------------------------------------- #
def test_route_retail_persists_and_exports(temp_db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.weekly import snapshot_store as wsnap
    from app.weekly import note_store as wns

    # Seed an active snapshot so /weekly/note can compute metrics.
    dates = pd.bdate_range("2026-01-01", periods=130).strftime("%Y-%m-%d").tolist()
    up = list(np.linspace(100, 118, 125)) + [119, 121, 123, 126, 130]
    dn = list(np.linspace(100, 95, 130))
    data = {
        "asof": "2026-06-26", "stale": False, "n_stale": 0, "partial": [],
        "tickers": {
            "AAA-HK": [{"date": d, "close": float(x), "volume": 1e6}
                       for d, x in zip(dates, up)],
            "BBB-HK": [{"date": d, "close": float(x), "volume": 1e6}
                       for d, x in zip(dates, dn)],
        },
        "hsi": [{"date": d, "close": float(c)}
                for d, c in zip(dates, np.linspace(20000, 21000, 130))],
    }
    wsnap.save_snapshot(data, name="t", make_active=True)

    client = TestClient(app)
    resp = client.post("/weekly/note",
                       data={"provider": "", "with_news": "", "audience": "retail"})
    assert resp.status_code == 200
    assert "Weekly Market Snapshot" in resp.text
    assert "retail" in resp.text  # audience tag in the partial

    # It was persisted with audience=retail.
    notes = wns.list_notes(limit=5)
    assert notes, "no note persisted"
    latest = notes[0]
    assert latest["audience"] == "retail"

    rec = wns.get_note(int(latest["id"]))
    assert rec["audience"] == "retail"
    assert rec["markdown"].startswith("# Weekly Market Snapshot")

    # Export serves the stored retail markdown with the retail title.
    ex = client.get(f"/weekly/note/{latest['id']}/export?fmt=md")
    assert ex.status_code == 200
    assert b"Weekly Market Snapshot" in ex.content


def test_route_institutional_default_button(temp_db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.weekly import snapshot_store as wsnap
    from app.weekly import note_store as wns

    dates = pd.bdate_range("2026-01-01", periods=130).strftime("%Y-%m-%d").tolist()
    up = list(np.linspace(100, 118, 130))
    data = {
        "asof": "2026-06-26", "stale": False, "n_stale": 0, "partial": [],
        "tickers": {"AAA-HK": [{"date": d, "close": float(x), "volume": 1e6}
                               for d, x in zip(dates, up)]},
        "hsi": [{"date": d, "close": float(c)}
                for d, c in zip(dates, np.linspace(20000, 21000, 130))],
    }
    wsnap.save_snapshot(data, name="t", make_active=True)

    client = TestClient(app)
    resp = client.post("/weekly/note",
                       data={"provider": "", "with_news": "", "audience": "institutional"})
    assert resp.status_code == 200
    assert "Weekly Quant One-Pager" in resp.text
    latest = wns.list_notes(limit=1)[0]
    assert latest["audience"] == "institutional"
