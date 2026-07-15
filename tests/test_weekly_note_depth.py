"""Phase D weekly-note follow-up: deeper Key Takeaways + Data observations,
unmissable as-of date, and a Fundamentals & attribution table sorted by 1W move.

Covers, per the objective:
  (a) render_fundamentals_table sorts rows by ret_1w DESC, NaN-safe (None last);
  (b) _staleness_banner emits a bold standalone 'Data as of:' line distinct from
      the staleness warning when stale, and just the bold line when not stale;
  (c) render_metric_tables emits an as-of caption before the first sub-table;
  (d) build_takeaways_prompt requests risk-adjusted momentum, a valuation anchor,
      and a watch-item bullet;
  (e) build_observations_prompt requests valuation/momentum for the top names and
      volume-confirmation callouts;
  (f) render_takeaways_deterministic surfaces a fwd-P/E-vs-sector or watch line
      when fundamentals are present, and is non-empty / crash-free with none.
"""
import re

from app.weekly import note as N


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_md_table_rows(md: str, header_first_col: str = "Symbol"):
    """Return the data rows (list of cell-lists) of the first markdown table whose
    header row begins with ``header_first_col``. Skips the header + separator."""
    lines = [l for l in md.splitlines() if l.strip().startswith("|")]
    rows = []
    in_tbl = False
    for l in lines:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if cells and cells[0] == header_first_col:
            in_tbl = True
            continue
        if in_tbl:
            if set("".join(cells)) <= set("-"):  # separator row
                continue
            if not cells or not cells[0]:
                break
            rows.append(cells)
    return rows


# ---------------------------------------------------------------------------
# (a) render_fundamentals_table sorted by 1W move, NaN-safe
# ---------------------------------------------------------------------------
def test_fundamentals_table_sorted_by_1w_desc_nan_last():
    # 4 movers, selected in a deliberately unsorted order; one has None ret_1w.
    metrics = {
        "catalyst_names": ["W", "X", "Y", "Z"],
        "per_ticker": {
            "W": {"ret_1w": 0.05, "has_fundamentals": True},
            "X": {"ret_1w": -0.10, "has_fundamentals": True},
            "Y": {"ret_1w": 0.20, "has_fundamentals": True},
            "Z": {"ret_1w": None, "has_fundamentals": True},
        },
    }
    out = N.render_fundamentals_table(metrics)
    rows = _parse_md_table_rows(out, "Symbol")
    symbols = [r[0] for r in rows]
    one_w = [r[1] for r in rows]
    # Descending by 1W: +0.20 (Y), +0.05 (W), -0.10 (X), then None (Z) last.
    assert symbols == ["Y", "W", "X", "Z"], symbols
    assert one_w == ["+20.0%", "+5.0%", "-10.0%", "—"], one_w
    # The None-ret ticker is strictly last.
    assert symbols[-1] == "Z"


def test_fundamentals_table_does_not_mutate_catalyst_names():
    metrics = {
        "catalyst_names": ["W", "X", "Y", "Z"],
        "per_ticker": {
            "W": {"ret_1w": 0.05, "has_fundamentals": True},
            "X": {"ret_1w": -0.10, "has_fundamentals": True},
            "Y": {"ret_1w": 0.20, "has_fundamentals": True},
            "Z": {"ret_1w": None, "has_fundamentals": True},
        },
    }
    N.render_fundamentals_table(metrics)
    # Original selection order preserved for other consumers.
    assert metrics["catalyst_names"] == ["W", "X", "Y", "Z"]


def test_fundamentals_table_nan_string_safe():
    # A non-numeric ret_1w must not crash and must sort to the bottom.
    metrics = {
        "catalyst_names": ["A", "B"],
        "per_ticker": {
            "A": {"ret_1w": "oops", "has_fundamentals": True},
            "B": {"ret_1w": 0.03, "has_fundamentals": True},
        },
    }
    out = N.render_fundamentals_table(metrics)
    rows = _parse_md_table_rows(out, "Symbol")
    assert [r[0] for r in rows] == ["B", "A"]


# ---------------------------------------------------------------------------
# (b) _staleness_banner — bold 'Data as of:' distinct from the warning
# ---------------------------------------------------------------------------
def test_staleness_banner_fresh_is_bold_asof_only():
    out = N._staleness_banner({"asof": "2026-06-26", "stale": False})
    assert out == "**Data as of: 2026-06-26**"
    assert "⚠" not in out


def test_staleness_banner_stale_has_distinct_bold_and_warning_lines():
    out = N._staleness_banner(
        {"asof": "2026-06-26", "stale": True, "n_stale": 3}
    )
    lines = [l for l in out.splitlines() if l.strip()]
    # First line: the bold as-of line, standalone (no warning merged in).
    assert lines[0] == "**Data as of: 2026-06-26**"
    assert "⚠" not in lines[0]
    # A separate line carries the staleness warning.
    warn = "\n".join(lines[1:])
    assert "⚠" in warn
    assert "3 business days old" in warn


# ---------------------------------------------------------------------------
# (c) render_metric_tables — as-of caption before the first sub-table
# ---------------------------------------------------------------------------
def test_metric_tables_have_asof_caption_before_first_table():
    md = N.render_metric_tables({"asof": "2026-06-26"})
    assert "_All figures below as of 2026-06-26._" in md
    caption_pos = md.index("_All figures below as of 2026-06-26._")
    first_tbl_pos = md.index("Movers & shakers")
    assert caption_pos < first_tbl_pos


# ---------------------------------------------------------------------------
# (d) build_takeaways_prompt — deeper instructions
# ---------------------------------------------------------------------------
def test_takeaways_prompt_requests_depth():
    prompt = N.build_takeaways_prompt({"asof": "2026-06-26"})
    low = prompt.lower()
    assert "risk-adjusted momentum" in low
    assert "valuation anchor" in low
    assert "watch item" in low
    # Asks for the deeper 4-6 bullet range (not the old 3-4).
    assert "4-6" in prompt


# ---------------------------------------------------------------------------
# (e) build_observations_prompt — valuation/momentum + volume confirmation
# ---------------------------------------------------------------------------
def test_observations_prompt_requests_valuation_momentum_and_volume():
    prompt = N.build_observations_prompt({"asof": "2026-06-26"})
    low = prompt.lower()
    assert "valuation-vs-sector" in low or "valuation vs sector" in low
    assert "momentum" in low and "revision" in low
    assert "volume confirmation" in low
    # Structure rules must still be present (addition, not rewrite).
    assert "PLAIN ENGLISH" in prompt
    assert "do NOT" in prompt or "do not" in low


# ---------------------------------------------------------------------------
# (f) render_takeaways_deterministic — richer with fundamentals, safe without
# ---------------------------------------------------------------------------
def _metrics_with_fundamentals_for_takeaways():
    """A top gainer carrying a cheap fwd-P/E-vs-sector read + an EPS-cut loser,
    shaped like the mover entries metrics.compute_weekly_metrics emits."""
    gainer = {
        "symbol": "AAA-HK", "company_name": "Alpha Retail", "ret_1w": 0.20,
        "fwd_pe": 10.0, "sector_median_fwd_pe": 20.0, "valuation_vs_sector": "cheap",
        "ret_sigma": 3.2, "z_1w": 3.2,
        "attribution": {"attribution": "Stock-specific", "peer_median_1w": 0.01},
    }
    loser = {
        "symbol": "BBB-HK", "company_name": "Beta Energy", "ret_1w": -0.12,
        "eps_revision_dir": "down", "eps_revision_pct": -0.15,
        "attribution": {"attribution": "Stock-specific", "peer_median_1w": -0.01},
    }
    return {
        "asof": "2026-06-26",
        "hsi": {"ret_1w": 0.01, "ret_ytd": 0.05, "trend": "uptrend"},
        "movers": {"gainers_1w": [gainer], "losers_1w": [loser], "extremes": [gainer]},
    }


def test_takeaways_deterministic_surfaces_valuation_and_watch():
    out = N.render_takeaways_deterministic(_metrics_with_fundamentals_for_takeaways())
    assert out.strip()
    low = out.lower()
    # A fwd-P/E-vs-sector line for the top mover.
    assert "valuation:" in low and "cheap" in low and "forward p/e" in low
    # An explicit watch line.
    assert "watch:" in low


def test_takeaways_deterministic_no_fundamentals_still_nonempty():
    # No movers/fundamentals at all -> still returns a non-empty bullet, no crash.
    out = N.render_takeaways_deterministic({})
    assert out.strip()
    assert out.strip().startswith("-")


def test_takeaways_deterministic_watch_prefers_eps_cut():
    # With an EPS cut present, the watch line should reference the cut.
    m = _metrics_with_fundamentals_for_takeaways()
    out = N.render_takeaways_deterministic(m)
    watch_lines = [l for l in out.splitlines() if l.lower().startswith("- watch:")]
    assert watch_lines
    assert any("eps cut" in l.lower() or "eps" in l.lower() for l in watch_lines)
