"""Phase D weekly metrics: returns / volume / HSI-relative / momentum / vol —
verified against hand-computed fixtures. Pure, NaN-safe, never raises, JSON-safe.
"""
import json
import math

import numpy as np
import pandas as pd

from app.weekly import metrics as M


def _dates(n):
    return pd.bdate_range("2026-01-01", periods=n).strftime("%Y-%m-%d").tolist()


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


def test_window_return_simple_pct():
    # 130 closes; last 5td move from index -6 to -1.
    closes = list(range(100, 230))  # 100..229, len 130
    s = M._series(_recs(closes), "close")
    # 1W = P[-1]/P[-6]-1 = 229/224 - 1
    r1w = M._window_return(s, M.W_1W)
    assert math.isclose(r1w, 229 / 224 - 1, rel_tol=1e-9)
    # 1M = P[-1]/P[-22]-1
    r1m = M._window_return(s, M.W_1M)
    assert math.isclose(r1m, 229 / (229 - 21) - 1, rel_tol=1e-9)


def test_ann_vol_matches_numpy():
    rng = np.random.default_rng(7)
    rets = rng.normal(0, 0.01, 200)
    prices = [100.0]
    for r in rets:
        prices.append(prices[-1] * (1 + r))
    s = M._series(_recs(prices), "close")
    got = M._ann_vol(s, M.VOL_20)
    # hand: stdev of last 20 daily simple returns * sqrt(252)
    dr = pd.Series(prices).pct_change().dropna().tail(20)
    expect = dr.std(ddof=1) * math.sqrt(252)
    assert math.isclose(got, expect, rel_tol=1e-9)


def test_volume_trend_ratio_and_spike():
    # 30 days: first 25 at 1e6, last 5 at [4e6,1e6,1e6,1e6,1e6]
    closes = list(np.linspace(100, 110, 30))
    vols = [1e6] * 25 + [4e6, 1e6, 1e6, 1e6, 1e6]
    vt = M._volume_trend(M._series(_recs(closes, vols), "volume"))
    # week avg = (4+1+1+1+1)/5 = 1.6e6; ADV20 over the 20 bars before the week = 1e6
    assert math.isclose(vt["week_avg_vol"], 1_600_000.0, rel_tol=1e-9)
    assert math.isclose(vt["adv_20d"], 1_000_000.0, rel_tol=1e-9)
    assert math.isclose(vt["vol_ratio"], 1.6, rel_tol=1e-9)
    assert math.isclose(vt["max_spike_ratio"], 4.0, rel_tol=1e-9)


def test_hsi_relative_is_stock_minus_hsi():
    # Stock up exactly 10% over 5td; HSI up exactly 4% over 5td.
    stock = [100.0] * 125 + [100, 100, 100, 100, 110.0]  # last/(-6)=110/100
    hsi = [100.0] * 125 + [100, 100, 100, 100, 104.0]
    snap = {"asof": "2026-06-26", "tickers": {"AAA": _recs(stock)}, "hsi": _hsi(hsi)}
    out = M.compute_weekly_metrics(snap)
    m = out["per_ticker"]["AAA"]
    assert math.isclose(m["ret_1w"], 0.10, rel_tol=1e-9)
    assert math.isclose(out["hsi"]["ret_1w"], 0.04, rel_tol=1e-9)
    # relative = stock 1W minus HSI 1W
    assert math.isclose(m["rel_1w"], 0.10 - 0.04, rel_tol=1e-9)


def test_momentum_risk_adjusted_is_3m_over_20dvol():
    rng = np.random.default_rng(3)
    rets = rng.normal(0.001, 0.012, 200)
    prices = [50.0]
    for r in rets:
        prices.append(prices[-1] * (1 + r))
    snap = {"asof": "2026-06-26", "tickers": {"X": _recs(prices)},
            "hsi": _hsi(list(np.linspace(100, 105, len(prices)))[: len(prices)])}
    out = M.compute_weekly_metrics(snap)
    m = out["per_ticker"]["X"]
    assert m["mom_3m"] == m["ret_3m"]
    if m["risk_adj_mom"] is not None:
        assert math.isclose(m["risk_adj_mom"], m["ret_3m"] / m["vol_20d"], rel_tol=1e-9)


def test_elevated_flag_when_20d_exceeds_60d():
    # Calm for 60 days then a volatile last 20 days.
    calm = list(100 + np.cumsum(np.random.default_rng(1).normal(0, 0.05, 80)))
    wild = list(calm[-1] + np.cumsum(np.random.default_rng(2).normal(0, 3.0, 30)))
    prices = calm + wild
    s = M._series(_recs(prices), "close")
    v20 = M._ann_vol(s, M.VOL_20)
    v60 = M._ann_vol(s, M.VOL_60)
    assert v20 is not None and v60 is not None and v20 > v60
    out = M.compute_weekly_metrics({"asof": "x", "tickers": {"W": _recs(prices)}, "hsi": []})
    assert out["per_ticker"]["W"]["vol_elevated"] is True


def test_ytd_return_from_year_start():
    # Build dates spanning the year boundary: Dec 2025 into 2026.
    ds = pd.bdate_range("2025-12-15", periods=140)
    prices = list(np.linspace(100, 150, 140))
    recs = [{"date": d.strftime("%Y-%m-%d"), "close": float(p), "volume": 1e6}
            for d, p in zip(ds, prices)]
    s = M._series(recs, "close")
    r = M._ytd_return(s)
    # anchor = last close before 2026-01-01; end = last close. Both positive, <50%.
    assert r is not None and r > 0


def test_movers_and_catalyst_names():
    up = [100.0] * 125 + [100, 100, 100, 100, 130.0]      # +30% 1W
    flat = [100.0] * 130
    dn = [100.0] * 125 + [100, 100, 100, 100, 80.0]       # -20% 1W
    snap = {"asof": "2026-06-26",
            "tickers": {"UP": _recs(up), "FLAT": _recs(flat), "DN": _recs(dn)},
            "hsi": _hsi([100.0] * 130)}
    out = M.compute_weekly_metrics(snap)
    g = out["movers"]["gainers_1w"]
    losers = out["movers"]["losers_1w"]
    assert g[0]["symbol"] == "UP"
    assert losers[0]["symbol"] == "DN"
    # catalyst names include the top gainer and top loser
    assert "UP" in out["catalyst_names"] and "DN" in out["catalyst_names"]


def test_never_raises_and_json_safe_on_garbage():
    # empty
    e = M.compute_weekly_metrics({})
    json.dumps(e)
    assert e["meta"]["n_tickers"] == 0
    assert e["hsi"]["loaded"] is False
    # short / malformed series must not raise
    bad = {"asof": None,
           "tickers": {"S": [{"date": "2026-01-01", "close": None, "volume": None}],
                       "T": []},
           "hsi": [{"date": "x", "close": "oops"}]}
    out = M.compute_weekly_metrics(bad)
    json.dumps(out)
    assert out["per_ticker"]["S"]["ret_1w"] is None


def test_dislocation_detected_for_big_move_high_z():
    rng = np.random.default_rng(9)
    base = list(100 + np.cumsum(rng.normal(0, 0.2, 124)))
    # final week: a sharp +15% jump well outside the stock's own 5td history
    prices = base + [base[-1], base[-1], base[-1], base[-1], base[-1] * 1.15]
    out = M.compute_weekly_metrics(
        {"asof": "x", "tickers": {"D": _recs(prices)}, "hsi": _hsi([100.0] * len(prices))})
    syms = [d["symbol"] for d in out["opportunities"]["dislocations"]]
    assert "D" in syms
