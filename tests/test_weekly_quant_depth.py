"""Phase D-3 Wave 1: dollar liquidity, market breadth, beta/alpha, and sector
rotation — verified against hand-computed fixtures. Pure, NaN-safe, never raise;
old snapshots without volume/sector still render (blocks omitted / n/a).
"""
import math

import numpy as np
import pandas as pd

from app.weekly import metrics as M
from app.weekly import note as N


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


# ---------------------------------------------------------------------------
# #4 Dollar liquidity + fmt_dollars
# ---------------------------------------------------------------------------
def test_dollar_liquidity_math():
    # 30 bars. Constant price 10, volume 1e6 except a spike of 5e6 on the last day.
    closes = [10.0] * 30
    vols = [1e6] * 29 + [5e6]
    close = M._series(_recs(closes, vols), "close")
    volume = M._series(_recs(closes, vols), "volume")
    dl = M._dollar_liquidity(close, volume)
    # advv_20d = mean(close*volume) over the 20 bars just before the last 5 td.
    # bars -25..-6 all at 10*1e6 = 1e7 -> mean 1e7.
    assert math.isclose(dl["advv_20d"], 1e7, rel_tol=1e-9)
    # week_dollar_vol = sum of last 5 td dollar volume = 4*(1e7) + (10*5e6=5e7)
    #                 = 4e7 + 5e7 = 9e7.
    assert math.isclose(dl["week_dollar_vol"], 9e7, rel_tol=1e-9)
    # dollar_spike_ratio = max single-day $vol in last 5 td (5e7) / advv_20d (1e7) = 5.
    assert math.isclose(dl["dollar_spike_ratio"], 5.0, rel_tol=1e-9)


def test_dollar_liquidity_no_volume_none():
    closes = [10.0] * 30
    close = M._series(_recs(closes), "close")
    empty = pd.Series(dtype="float64")
    dl = M._dollar_liquidity(close, empty)
    assert dl["advv_20d"] is None
    assert dl["week_dollar_vol"] is None
    assert dl["dollar_spike_ratio"] is None


def test_fmt_dollars_scales():
    assert N.fmt_dollars(1.2e9) == "$1.2b"
    assert N.fmt_dollars(85e6) == "$85m"
    assert N.fmt_dollars(950e3) == "$950k"
    assert N.fmt_dollars(120) == "$120"
    assert N.fmt_dollars(None) == "\u2014"
    assert N.fmt_dollars(float("nan")) == "\u2014"
    assert N.fmt_dollars("not a number") == "\u2014"


# ---------------------------------------------------------------------------
# #1 Market breadth
# ---------------------------------------------------------------------------
def _pt(ret_1w, dv=None, sector=None, ret_ytd=None):
    return {"ret_1w": ret_1w, "week_dollar_vol": dv, "sector": sector,
            "ret_ytd": ret_ytd}


def test_breadth_counts_and_ratio():
    per = {
        "A": _pt(0.05, dv=100.0),   # up
        "B": _pt(0.02, dv=50.0),    # up
        "C": _pt(-0.03, dv=30.0),   # down
        "D": _pt(0.0005, dv=10.0),  # flat (within +/-0.001)
        "E": _pt(None),             # excluded (no valid ret)
    }
    b = M.breadth_metrics(per)
    assert b["advancers"] == 2
    assert b["decliners"] == 1
    assert b["flat"] == 1
    assert b["n_valid"] == 4
    # ratio = 2 / (2+1)
    assert math.isclose(b["breadth_ratio"], 2 / 3, rel_tol=1e-9)
    assert math.isclose(b["up_dollar_vol"], 150.0, rel_tol=1e-9)
    assert math.isclose(b["down_dollar_vol"], 30.0, rel_tol=1e-9)


def test_breadth_ratio_none_when_no_directional():
    per = {"A": _pt(0.0), "B": _pt(0.0005)}
    b = M.breadth_metrics(per)
    assert b["advancers"] == 0 and b["decliners"] == 0 and b["flat"] == 2
    assert b["breadth_ratio"] is None


def test_breadth_new_high_low_detection():
    # A: latest close is the series max -> new high.
    a = _recs([10, 12, 11, 13, 20])
    # B: latest close is the series min -> new low.
    bb = _recs([50, 40, 30, 25, 10])
    snap = {"asof": "2025-07-14", "tickers": {"A-HK": a, "B-HK": bb},
            "hsi": _hsi([100, 101, 102, 103, 104])}
    m = M.compute_weekly_metrics(snap)
    assert "A-HK" in m["breadth"]["new_highs"]
    assert "B-HK" in m["breadth"]["new_lows"]


def test_breadth_divergence_narrow_tape():
    # HSI up (>+0.2%), breadth < 0.40 -> narrow tape.
    per = {f"D{i}": _pt(-0.02, dv=10.0) for i in range(7)}
    per["U1"] = _pt(0.02, dv=10.0)
    per["U2"] = _pt(0.02, dv=10.0)
    b = M.breadth_metrics(per, hsi_ret_1w=0.01)
    assert b["breadth_ratio"] < 0.40
    assert b["divergence"] is not None and "Narrow tape" in b["divergence"]


def test_breadth_divergence_hidden_strength():
    # HSI down (<-0.2%), breadth > 0.60 -> hidden strength.
    per = {f"U{i}": _pt(0.02, dv=10.0) for i in range(7)}
    per["D1"] = _pt(-0.02, dv=10.0)
    per["D2"] = _pt(-0.02, dv=10.0)
    b = M.breadth_metrics(per, hsi_ret_1w=-0.01)
    assert b["breadth_ratio"] > 0.60
    assert b["divergence"] is not None and "Hidden strength" in b["divergence"]


def test_breadth_divergence_none_branch():
    # HSI up but breadth healthy -> no divergence.
    per = {"U1": _pt(0.02, dv=10.0), "U2": _pt(0.02, dv=10.0),
           "D1": _pt(-0.01, dv=10.0)}
    b = M.breadth_metrics(per, hsi_ret_1w=0.01)
    assert b["breadth_ratio"] >= 0.40
    assert b["divergence"] is None


# ---------------------------------------------------------------------------
# #3 Beta / alpha
# ---------------------------------------------------------------------------
def test_realized_beta_noiseless_1p5x():
    # Stock daily returns = 1.5 * HSI daily returns, exactly. beta ~ 1.5.
    rng = np.random.default_rng(3)
    hsi_r = rng.normal(0, 0.01, 60)
    stock_r = 1.5 * hsi_r
    idx = pd.to_datetime(_dates(60))
    beta = M.realized_beta(pd.Series(stock_r, index=idx),
                           pd.Series(hsi_r, index=idx))
    assert beta is not None
    assert math.isclose(beta, 1.5, rel_tol=1e-6)


def test_realized_beta_insufficient_overlap_none():
    rng = np.random.default_rng(4)
    hsi_r = rng.normal(0, 0.01, 30)   # only 30 obs < 40 min
    stock_r = 1.2 * hsi_r
    idx = pd.to_datetime(_dates(30))
    beta = M.realized_beta(pd.Series(stock_r, index=idx),
                           pd.Series(hsi_r, index=idx))
    assert beta is None


def test_realized_beta_clip():
    # Stock = 10x HSI -> raw beta 10, clipped to BETA_CLIP_HIGH (5.0).
    rng = np.random.default_rng(5)
    hsi_r = rng.normal(0, 0.01, 60)
    stock_r = 10.0 * hsi_r
    idx = pd.to_datetime(_dates(60))
    beta = M.realized_beta(pd.Series(stock_r, index=idx),
                           pd.Series(hsi_r, index=idx))
    assert beta == M.BETA_CLIP_HIGH


def test_alpha_1w_formula_in_compute():
    # Construct a stock that tracks the HSI at 1.5x so beta~1.5 and alpha can be
    # checked against ret_1w - 1.5 * hsi_ret_1w.
    n = 80
    rng = np.random.default_rng(6)
    hsi_r = rng.normal(0.0005, 0.008, n - 1)
    hsi_px = [10000.0]
    for r in hsi_r:
        hsi_px.append(hsi_px[-1] * (1 + r))
    stock_px = [100.0]
    for r in hsi_r:
        stock_px.append(stock_px[-1] * (1 + 1.5 * r))
    snap = {
        "asof": "2025-07-14",
        "tickers": {"S-HK": _recs(stock_px)},
        "hsi": _hsi(hsi_px),
    }
    m = M.compute_weekly_metrics(snap)
    rec = m["per_ticker"]["S-HK"]
    assert rec["beta_60d"] is not None
    assert math.isclose(rec["beta_60d"], 1.5, rel_tol=0.05)
    h1w = m["hsi"]["ret_1w"]
    expect = rec["ret_1w"] - rec["beta_60d"] * h1w
    assert math.isclose(rec["alpha_1w"], expect, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# #6 Sector rotation
# ---------------------------------------------------------------------------
def test_sector_rotation_medians_and_ranks():
    per = {
        "T1": _pt(0.05, sector="Tech", ret_ytd=0.20),
        "T2": _pt(0.03, sector="Tech", ret_ytd=0.10),
        "E1": _pt(-0.02, sector="Energy", ret_ytd=-0.05),
        "E2": _pt(-0.04, sector="Energy", ret_ytd=-0.15),
    }
    sr = M.sector_rotation(per, None)
    assert sr["note"] == "no history yet"
    secs = {s["sector"]: s for s in sr["sectors"]}
    # Tech median 1W = median(0.05, 0.03) = 0.04; Energy = median(-0.02,-0.04)=-0.03
    assert math.isclose(secs["Tech"]["ret_1w_med"], 0.04, rel_tol=1e-9)
    assert math.isclose(secs["Energy"]["ret_1w_med"], -0.03, rel_tol=1e-9)
    # Tech leads -> rank 1.
    assert secs["Tech"]["rank"] == 1
    assert secs["Energy"]["rank"] == 2
    assert secs["Tech"]["adv"] == 2 and secs["Tech"]["dec"] == 0
    assert secs["Energy"]["dec"] == 2


def test_sector_rotation_in_out_tags():
    # This week: Sector A rank 1, B rank 2, C rank 3, D rank 4.
    per = {
        "A1": _pt(0.10, sector="A"),
        "B1": _pt(0.05, sector="B"),
        "C1": _pt(-0.02, sector="C"),
        "D1": _pt(-0.08, sector="D"),
    }
    # Prev: A was rank 4, D was rank 1 -> A jumps 3 (rotation in), D drops 3 (out).
    prev = [
        {"sector": "D", "rank": 1},
        {"sector": "C", "rank": 2},
        {"sector": "B", "rank": 3},
        {"sector": "A", "rank": 4},
    ]
    sr = M.sector_rotation(per, prev)
    assert sr["note"] is None
    secs = {s["sector"]: s for s in sr["sectors"]}
    assert secs["A"]["rank"] == 1 and secs["A"]["prev_rank"] == 4
    assert secs["A"]["rotation"] == "rotation in"
    assert secs["D"]["rank"] == 4 and secs["D"]["prev_rank"] == 1
    assert secs["D"]["rotation"] == "rotation out"
    # B and C moved only 1 rank -> no tag.
    assert secs["B"]["rotation"] is None
    assert secs["C"]["rotation"] is None


def test_sector_rotation_no_sectors():
    per = {"X": _pt(0.01, sector=None), "Y": _pt(-0.01, sector="")}
    sr = M.sector_rotation(per, None)
    assert sr["sectors"] == []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _synthetic_snapshot(with_volume=True, with_sector=True):
    n = 140
    rng = np.random.default_rng(9)
    hsi_r = rng.normal(0.0004, 0.008, n - 1)
    hsi_px = [10000.0]
    for r in hsi_r:
        hsi_px.append(hsi_px[-1] * (1 + r))

    def mk(base, drift, vol, seed, volbase):
        rr = np.random.default_rng(seed)
        rets = rr.normal(drift, vol, n - 1)
        px = [base]
        for r in rets:
            px.append(px[-1] * (1 + r))
        if with_volume:
            return _recs(px, [volbase] * n)
        # No volume field at all (old lean price-only template).
        ds = _dates(len(px))
        return [{"date": d, "close": float(p)} for d, p in zip(ds, px)]

    tickers = {
        "AAA-HK": mk(50, 0.002, 0.01, 1, 5e6),
        "BBB-HK": mk(30, -0.003, 0.012, 2, 2e5),
        "CCC-HK": mk(80, 0.0005, 0.008, 3, 1e7),
        "DDD-HK": mk(20, -0.001, 0.02, 4, 3e6),
    }
    fundamentals = None
    if with_sector:
        fundamentals = {
            "AAA-HK": {"factset_sector": "Technology", "company_name": "Alpha"},
            "BBB-HK": {"factset_sector": "Energy", "company_name": "Beta"},
            "CCC-HK": {"factset_sector": "Technology", "company_name": "Cee"},
            "DDD-HK": {"factset_sector": "Energy", "company_name": "Dee"},
        }
    snap = {"asof": "2025-07-14", "tickers": tickers, "hsi": _hsi(hsi_px)}
    if fundamentals:
        snap["fundamentals"] = fundamentals
    return snap


def test_render_sections_present_with_data():
    m = M.compute_weekly_metrics(_synthetic_snapshot())
    md = N._no_key_markdown(m)
    assert "## Market internals" in md
    assert "## Sector scoreboard" in md
    assert "$ADV" in md
    # Section order: Market internals BEFORE Sector scoreboard BEFORE glossary.
    assert md.index("## Market internals") < md.index("## Sector scoreboard")


def test_render_sections_omitted_when_no_volume_no_sector():
    # No volume AND no sector -> breadth still has A/D (returns exist) but no $vol,
    # sector scoreboard omitted (no sectors). Must not crash.
    snap = _synthetic_snapshot(with_volume=False, with_sector=False)
    m = M.compute_weekly_metrics(snap)
    md = N._no_key_markdown(m)
    # Sector scoreboard omitted (no sectors).
    assert "## Sector scoreboard" not in md
    # No $ADV values render (all em-dash) but the code never crashes.
    assert isinstance(md, str) and "## Computed metrics" in md
    # Up/down $ vol are None (no volume).
    assert m["breadth"]["up_dollar_vol"] is None


def test_render_market_internals_empty_when_no_returns():
    m = {"breadth": {"n_valid": 0}}
    assert N.render_market_internals(m) == ""
    assert N.render_sector_scoreboard({"sector_rotation": {"sectors": []}}) == ""


# ---------------------------------------------------------------------------
# Integration: full synthetic snapshot -> metrics populated
# ---------------------------------------------------------------------------
def test_compute_weekly_metrics_integration_fields():
    m = M.compute_weekly_metrics(_synthetic_snapshot())
    assert "breadth" in m and "sector_rotation" in m
    assert m["breadth"]["n_valid"] >= 1
    assert m["sector_rotation"]["sectors"]
    # Per-ticker Wave-1 fields present.
    rec = m["per_ticker"]["AAA-HK"]
    for k in ("advv_20d", "week_dollar_vol", "dollar_spike_ratio",
              "beta_60d", "alpha_1w"):
        assert k in rec
    assert rec["advv_20d"] is not None
    assert rec["beta_60d"] is not None
    # Movers carry alpha leaders/laggards.
    assert "alpha_leaders" in m["movers"] and "alpha_laggards" in m["movers"]


def test_prev_note_rotation_wiring_via_compute():
    snap = _synthetic_snapshot()
    m1 = M.compute_weekly_metrics(snap)
    # Feed m1 as the previous note; ranks unchanged -> no rotation tags but note
    # is no longer "no history yet".
    m2 = M.compute_weekly_metrics(snap, prev_note_metrics=m1)
    assert m2["sector_rotation"]["note"] is None
    for s in m2["sector_rotation"]["sectors"]:
        assert s["prev_rank"] is not None


def test_never_raises_on_empty_snapshot():
    m = M.compute_weekly_metrics({})
    assert m["breadth"]["n_valid"] == 0
    assert m["sector_rotation"]["sectors"] == []
    # Rendering an empty metrics dict must not crash.
    assert isinstance(N._no_key_markdown(m), str)
