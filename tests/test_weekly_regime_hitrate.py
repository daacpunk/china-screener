"""Phase D-3 Wave 2: cross-sectional dispersion & correlation regime (#2) and
the hit-rate scorecard (#5). Pure, NaN/None-safe, never raise; old snapshots and
first-ever runs (no prior notes) render fine.
"""
import math

import numpy as np
import pandas as pd

from app.weekly import history as H
from app.weekly import metrics as M
from app.weekly import note as N
from app.weekly import note_store as NS


def _dates(n):
    return pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d").tolist()


def _recs(prices, vols=None):
    ds = _dates(len(prices))
    out = []
    for i, (d, p) in enumerate(zip(ds, prices)):
        v = float(vols[i]) if vols is not None else 1_000_000.0
        out.append({"date": d, "close": float(p), "volume": v})
    return out


def _hsi(prices):
    ds = _dates(len(prices))
    return [{"date": d, "close": float(p)} for d, p in zip(ds, prices)]


# ===========================================================================
# #2 Regime: dispersion & correlation
# ===========================================================================
def _series_from_returns(rets):
    idx = pd.to_datetime(_dates(len(rets)))
    return pd.Series(np.asarray(rets, dtype="float64"), index=idx)


def test_regime_high_corr_macro():
    # 6 names whose daily returns all move together (correlation ~ 1).
    n = 25
    base = np.random.default_rng(1).normal(0, 0.01, n)
    dr = {}
    for i in range(6):
        jitter = np.random.default_rng(100 + i).normal(0, 1e-5, n)
        dr[f"T{i}"] = _series_from_returns(base + jitter)
    per = {f"T{i}": {"ret_1w": 0.005 * i} for i in range(6)}
    r = M.regime_metrics(per, dr)
    assert r["avg_pairwise_corr_20d"] is not None
    assert r["avg_pairwise_corr_20d"] > 0.99
    assert r["tag"] == M.REGIME_TAG_MACRO
    assert r["n_names"] == 6


def test_regime_independent_wide_spread_idiosyncratic():
    # 6 names with independent daily returns (low corr) + a wide 1W spread.
    n = 25
    dr = {}
    for i in range(6):
        dr[f"T{i}"] = _series_from_returns(
            np.random.default_rng(200 + i).normal(0, 0.02, n))
    spread = [-0.09, -0.05, 0.0, 0.03, 0.07, 0.11]  # wide dispersion
    per = {f"T{i}": {"ret_1w": v} for i, v in enumerate(spread)}
    r = M.regime_metrics(per, dr)
    assert r["avg_pairwise_corr_20d"] is not None
    assert abs(r["avg_pairwise_corr_20d"]) < M.LOW_CORR
    assert r["xsec_dispersion_1w"] >= M.REGIME_DISP_HIGH
    assert r["tag"] == M.REGIME_TAG_IDIO


def test_regime_dispersion_matches_hand_calc():
    # 5 names, no daily-return matrix -> dispersion is sample stdev (ddof=1).
    vals = [0.02, -0.01, 0.05, -0.03, 0.00]
    per = {f"N{i}": {"ret_1w": v} for i, v in enumerate(vals)}
    r = M.regime_metrics(per, {})
    hand = float(np.std(np.asarray(vals), ddof=1))
    assert math.isclose(r["xsec_dispersion_1w"], hand, rel_tol=1e-9)
    # No correlation available (empty matrix).
    assert r["avg_pairwise_corr_20d"] is None
    assert r["n_names"] == 0


def test_regime_fewer_than_five_names_graceful():
    # Only 3 names -> dispersion None, corr None, tag falls back to Mixed.
    per = {"A": {"ret_1w": 0.01}, "B": {"ret_1w": -0.02}, "C": {"ret_1w": 0.03}}
    r = M.regime_metrics(per, {})
    assert r["xsec_dispersion_1w"] is None
    assert r["avg_pairwise_corr_20d"] is None
    assert r["tag"] == M.REGIME_TAG_MIXED
    assert r["n_names"] == 0


def test_regime_never_raises_on_garbage():
    # Non-dict per-ticker entries, junk daily returns -> no crash.
    per = {"A": None, "B": {"ret_1w": "x"}, "C": {"ret_1w": 0.02}}
    r = M.regime_metrics(per, {"A": "junk", "B": [1, 2, 3]})
    assert isinstance(r, dict) and "tag" in r


def test_regime_tag_rule_direct():
    # Correlation is primary: high corr -> macro regardless of dispersion.
    assert M._regime_tag(0.60, 0.05) == M.REGIME_TAG_MACRO
    # Low corr + wide dispersion -> idiosyncratic.
    assert M._regime_tag(0.10, 0.04) == M.REGIME_TAG_IDIO
    # Low corr + tight dispersion -> nothing to pick -> macro.
    assert M._regime_tag(0.10, 0.005) == M.REGIME_TAG_MACRO
    # Middle corr band + middle dispersion -> mixed.
    assert M._regime_tag(0.35, 0.02) == M.REGIME_TAG_MIXED
    # No corr, dispersion-only reads.
    assert M._regime_tag(None, 0.05) == M.REGIME_TAG_IDIO
    assert M._regime_tag(None, 0.005) == M.REGIME_TAG_MACRO
    assert M._regime_tag(None, None) == M.REGIME_TAG_MIXED


# ===========================================================================
# #5 Hit-rate scorecard
# ===========================================================================
def _prior_note(asof, dislocations):
    return {"asof": asof,
            "metrics": {"opportunities": {"dislocations": dislocations}}}


def test_hit_rate_hit_miss_and_skip():
    prior = [_prior_note("2025-06-01", [
        {"symbol": "A", "ret_1w": -0.20},   # oversold flag -> expect bounce
        {"symbol": "B", "ret_1w": 0.30},    # overbought flag -> expect drop
        {"symbol": "C", "ret_1w": -0.15},   # not in current series -> skip
    ])]
    # Current series: A rose +0.10 from the as-of (opposite -> hit); B kept
    # rising (same sign -> miss); C absent.
    current = {
        "A": [{"date": "2025-06-02", "close": 100.0},
              {"date": "2025-07-14", "close": 110.0}],
        "B": [{"date": "2025-06-02", "close": 100.0},
              {"date": "2025-07-14", "close": 115.0}],
    }
    r = H.evaluate_hit_rate(prior, current, current_asof="2025-07-15")
    assert r["n_evaluated"] == 2   # C skipped
    by = {e["symbol"]: e for e in r["evaluated"]}
    assert "C" not in by
    # A: since_ret ~ +0.10, opposite sign to -0.20, |0.10| >= 0.25*0.20=0.05 -> hit.
    assert math.isclose(by["A"]["since_ret"], 0.10, rel_tol=1e-6)
    assert by["A"]["hit"] is True
    # B: since_ret ~ +0.15, SAME sign as +0.30 -> miss.
    assert by["B"]["hit"] is False
    assert r["n_hits"] == 1
    assert "1 of 2" in r["summary"]


def test_hit_rate_threshold_below_fraction_is_miss():
    # A oversold -0.20; bounced only +0.03 (< 0.25*0.20 = 0.05) -> miss.
    prior = [_prior_note("2025-06-01", [{"symbol": "A", "ret_1w": -0.20}])]
    current = {"A": [{"date": "2025-06-02", "close": 100.0},
                     {"date": "2025-07-14", "close": 103.0}]}
    r = H.evaluate_hit_rate(prior, current, current_asof="2025-07-15")
    assert r["n_evaluated"] == 1
    assert r["evaluated"][0]["hit"] is False
    assert r["n_hits"] == 0


def test_hit_rate_no_prior_insufficient():
    r = H.evaluate_hit_rate([], {"A": [{"date": "2025-01-01", "close": 1.0}]})
    assert r["n_evaluated"] == 0
    assert "Insufficient history" in r["summary"]


def test_hit_rate_start_is_on_or_after_asof():
    # The start close must be the first trading day ON/AFTER the prior as-of.
    prior = [_prior_note("2025-06-03", [{"symbol": "A", "ret_1w": -0.10}])]
    current = {"A": [
        {"date": "2025-06-01", "close": 90.0},   # before as-of -> ignored
        {"date": "2025-06-04", "close": 100.0},  # first on/after -> start
        {"date": "2025-07-14", "close": 120.0},  # latest -> end
    ]}
    r = H.evaluate_hit_rate(prior, current, current_asof="2025-07-15")
    e = r["evaluated"][0]
    assert math.isclose(e["since_ret"], 0.20, rel_tol=1e-9)  # 120/100 - 1
    assert e["hit"] is True


def test_hit_rate_never_raises_on_garbage():
    prior = [{"asof": None, "metrics": None}, None,
             {"asof": "2025-06-01", "metrics": {"opportunities": None}}]
    r = H.evaluate_hit_rate(prior, {"A": None}, current_asof="2025-07-15")
    assert isinstance(r, dict) and r["n_evaluated"] == 0


# ===========================================================================
# load_prior_note_metrics against a temp DB
# ===========================================================================
def test_load_prior_note_metrics_seeded(temp_db):
    m1 = {"asof": "2025-05-01", "opportunities": {"dislocations": []}}
    m2 = {"asof": "2025-05-08", "opportunities": {"dislocations": []}}
    m3 = {"asof": "2025-05-15", "opportunities": {"dislocations": []}}
    NS.save_note("2025-05-01", "p", m1, "md1", db_path=temp_db)
    NS.save_note("2025-05-08", "p", m2, "md2", db_path=temp_db)
    NS.save_note("2025-05-15", "p", m3, "md3", db_path=temp_db)
    got = H.load_prior_note_metrics(limit=8, db_path=temp_db)
    assert len(got) == 3
    # Most-recent first.
    assert [g["asof"] for g in got] == ["2025-05-15", "2025-05-08", "2025-05-01"]
    assert all(g["metrics"] for g in got)
    # exclude_asof drops the current one.
    got2 = H.load_prior_note_metrics(limit=8, exclude_asof="2025-05-15",
                                     db_path=temp_db)
    assert [g["asof"] for g in got2] == ["2025-05-08", "2025-05-01"]


def test_load_prior_note_metrics_skips_metricless(temp_db):
    NS.save_note("2025-05-01", "p", None, "md1", db_path=temp_db)  # no metrics
    NS.save_note("2025-05-08", "p", {"asof": "2025-05-08"}, "md2", db_path=temp_db)
    got = H.load_prior_note_metrics(limit=8, db_path=temp_db)
    assert len(got) == 1
    assert got[0]["asof"] == "2025-05-08"


def test_load_prior_note_metrics_empty_db(temp_db):
    assert H.load_prior_note_metrics(limit=8, db_path=temp_db) == []


# ===========================================================================
# Rendering
# ===========================================================================
def _synthetic_snapshot(n_names=6):
    n = 140
    rng = np.random.default_rng(9)
    hsi_r = rng.normal(0.0004, 0.008, n - 1)
    hsi_px = [10000.0]
    for r in hsi_r:
        hsi_px.append(hsi_px[-1] * (1 + r))
    tickers = {}
    fundamentals = {}
    for i in range(n_names):
        rr = np.random.default_rng(20 + i).normal(0.0, 0.02, n - 1)
        px = [50.0]
        for r in rr:
            px.append(px[-1] * (1 + r))
        tk = f"T{i}-HK"
        tickers[tk] = _recs(px)
        fundamentals[tk] = {"factset_sector": ("Tech" if i % 2 else "Energy"),
                            "company_name": f"Co{i}"}
    return {"asof": "2025-07-14", "tickers": tickers, "hsi": _hsi(hsi_px),
            "fundamentals": fundamentals}


def test_render_regime_line_in_market_internals():
    m = M.compute_weekly_metrics(_synthetic_snapshot())
    md = N._no_key_markdown(m)
    assert "## Market internals" in md
    assert "Regime:" in md


def test_render_scorecard_block_present_when_data():
    m = M.compute_weekly_metrics(_synthetic_snapshot())
    # Attach a hit_rate result with one evaluated hit.
    m["hit_rate"] = {
        "evaluated": [{"symbol": "T0-HK", "flagged_on": "2025-06-01",
                       "flag_ret": -0.2, "since_ret": 0.1, "hit": True}],
        "n_hits": 1, "n_evaluated": 1, "window_weeks": 8, "hit_fraction": 0.25,
        "definition": "rule", "summary": "1 of 1 have begun mean-reverting.",
    }
    block = N.render_scorecard(m)
    assert "Scorecard" in block
    assert "[OK]" in block
    md = N._no_key_markdown(m)
    assert "Scorecard - how prior calls played out" in md
    assert "mean-reverting" in md


def test_render_scorecard_insufficient_history_line():
    m = M.compute_weekly_metrics(_synthetic_snapshot())
    m["hit_rate"] = {
        "evaluated": [], "n_hits": 0, "n_evaluated": 0, "window_weeks": 8,
        "hit_fraction": 0.25, "definition": "rule",
        "summary": "Insufficient history - need >= 1 prior weekly note with "
                   "flagged dislocations.",
    }
    block = N.render_scorecard(m)
    assert "Insufficient history" in block
    # Must not crash rendering the full note.
    md = N._no_key_markdown(m)
    assert isinstance(md, str)
    assert "Insufficient history" in md


def test_render_regime_absent_when_no_data():
    # No regime key at all -> line is empty; render still works.
    assert N.render_regime_line({}) == ""
    assert N.render_scorecard({}) == ""


def test_compute_populates_regime():
    m = M.compute_weekly_metrics(_synthetic_snapshot())
    assert "regime" in m
    assert m["regime"]["tag"]
    assert m["regime"]["n_names"] >= 5


def test_build_note_flow_attaches_hit_rate():
    """A _build_note-style flow: compute metrics, then attach a hit_rate from a
    prior note whose flagged name reverses in the current snapshot."""
    snap = _synthetic_snapshot()
    metrics = M.compute_weekly_metrics(snap)
    # Prior note flagged T0-HK oversold; current series is the same snapshot, so
    # measure realized move from an early as-of to the latest close.
    early_asof = snap["tickers"]["T0-HK"][10]["date"]
    prior = [{"asof": early_asof,
              "metrics": {"opportunities": {"dislocations":
                          [{"symbol": "T0-HK", "ret_1w": -0.20}]}}}]
    current_series = {
        tk: [{"date": r["date"], "close": r["close"]} for r in recs]
        for tk, recs in snap["tickers"].items()
    }
    metrics["hit_rate"] = H.evaluate_hit_rate(
        prior, current_series, current_asof=snap["asof"])
    assert metrics["hit_rate"]["n_evaluated"] == 1
    # Rendering with the attached hit_rate must produce the scorecard block.
    md = N._no_key_markdown(metrics)
    assert "Scorecard - how prior calls played out" in md


def test_regime_and_hitrate_empty_snapshot_render():
    # First-ever run: empty snapshot, no prior notes -> everything graceful.
    m = M.compute_weekly_metrics({})
    assert m["regime"]["tag"] == M.REGIME_TAG_MIXED
    m["hit_rate"] = H.evaluate_hit_rate([], {})
    md = N._no_key_markdown(m)
    assert isinstance(md, str)
