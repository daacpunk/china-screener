"""z-score math, non-overlapping window logic, peer-divergence tagging, screen flow."""
import numpy as np
import pandas as pd

from app import screen_engine as se


def test_volatility_normalized_z_formula():
    # v2 default is RAW: z = r / (sigma*sqrt(h)). Pass demean=True for old behavior.
    r, mu, sigma, h = 0.10, 0.001, 0.02, 5
    # raw (default)
    expected_raw = r / (sigma * np.sqrt(h))
    assert abs(se.volatility_normalized_z(r, mu, sigma, h) - expected_raw) < 1e-12
    # demean (legacy) form
    expected_demean = (r - mu * h) / (sigma * np.sqrt(h))
    assert abs(se.volatility_normalized_z(r, mu, sigma, h, demean=True) - expected_demean) < 1e-12


def test_volatility_normalized_z_zero_vol_nan():
    assert np.isnan(se.volatility_normalized_z(0.1, 0.0, 0.0, 5))


def test_horizon_windows_non_overlapping():
    # Build a price path where we know exact returns.
    # 30 days; last price index 29.
    prices = pd.Series([float(100 + i) for i in range(30)])  # linear 100..129
    # Horizon A (1-week): last 5 td -> P[29]/P[24]-1 = 129/124 - 1
    r_a = se.horizon_return(prices, start_offset=5, end_offset=0)
    assert abs(r_a - (129 / 124 - 1)) < 1e-12
    # Horizon B (1m-ex-week): day -21 to -5 -> P[24]/P[8]-1 = 124/108 - 1
    r_b = se.horizon_return(prices, start_offset=21, end_offset=5)
    assert abs(r_b - (124 / 108 - 1)) < 1e-12
    # Windows are non-overlapping: A covers idx 24->29, B covers idx 8->24.
    # The shared boundary is index 24 (end of B == start of A) — no overlap of
    # the *return intervals* beyond the single shared anchor point.


def _synthetic_universe_and_prices():
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2024-01-01", periods=120)
    rows = []
    # two sub-industry peers that move together (sector move) + one idiosyncratic
    specs = {
        "AAA": dict(sub="Banks", shock=-0.20),   # idiosyncratic crash
        "BBB": dict(sub="Banks", shock=0.0),     # peer calm
        "CCC": dict(sub="Banks", shock=0.0),     # peer calm
        "DDD": dict(sub="Tech", shock=0.25),     # overbought rally
        "EEE": dict(sub="Tech", shock=0.0),
    }
    uni = []
    for t, sp in specs.items():
        base = 100.0
        rets = rng.normal(0.0002, 0.012, 120)
        if sp["shock"]:
            rets[-7:] += (1 + sp["shock"]) ** (1 / 7) - 1
        prices = base * np.cumprod(1 + rets)
        for d, p in zip(dates, prices):
            rows.append({"ticker": t, "date": d, "close": float(p), "volume": 1_000_000})
        uni.append({"ticker": t, "name": t, "sector": "X", "sub_industry": sp["sub"],
                    "index_weight": 1.0, "adv_usd_20d": 50_000_000, "below_floor": False})
    return pd.DataFrame(uni), pd.DataFrame(rows)


def test_peer_divergence_tagging():
    uni, prices = _synthetic_universe_and_prices()
    params = dict(se.DEFAULT_PARAMS)
    params["min_bars"] = 60
    res = se.run_screen(prices, uni, params)
    master = res["master"].set_index("ticker")
    # AAA crashed while its Banks peers were calm -> idiosyncratic
    assert master.loc["AAA", "dislocation_type"] == "IDIOSYNCRATIC"
    # peer_relative_z for AAA should be strongly negative
    assert master.loc["AAA", "peer_relative_z"] < -1.0


def test_ranking_by_abs_z():
    uni, prices = _synthetic_universe_and_prices()
    res = se.run_screen(prices, uni, se.DEFAULT_PARAMS)
    master = res["master"]
    abs_z = master["abs_z"].dropna().tolist()
    assert abs_z == sorted(abs_z, reverse=True), "master must be ranked by |z| desc"


def test_below_floor_excluded():
    uni, prices = _synthetic_universe_and_prices()
    uni.loc[uni["ticker"] == "EEE", "below_floor"] = True
    res = se.run_screen(prices, uni, se.DEFAULT_PARAMS)
    assert "EEE" not in res["master"]["ticker"].tolist()
    assert "EEE" in res["skipped"]["ticker"].tolist()


def test_min_bars_flagging():
    uni, prices = _synthetic_universe_and_prices()
    # truncate AAA to few bars
    short = prices[(prices["ticker"] != "AAA") | (prices.groupby("ticker").cumcount() < 10)]
    res = se.run_screen(short, uni, se.DEFAULT_PARAMS)
    skipped = res["skipped"]
    assert "AAA" in skipped["ticker"].tolist()


def test_screen_flow_non_empty_lists():
    """Synthetic flow: an oversold crash + overbought rally -> both playbooks
    non-empty and ranked (scored mode by score desc; master by |z| desc)."""
    uni, prices = _synthetic_universe_and_prices()
    res = se.run_screen(prices, uni, se.DEFAULT_PARAMS)
    assert len(res["oversold"]) > 0, "oversold-reversion list must be non-empty"
    assert len(res["overbought"]) > 0, "overbought-fade list must be non-empty"
    # scored mode (default): playbooks ranked by reversion_score / fade_score desc
    os_scores = res["oversold"]["reversion_score"].tolist()
    assert os_scores == sorted(os_scores, reverse=True)
    ob_scores = res["overbought"]["fade_score"].tolist()
    assert ob_scores == sorted(ob_scores, reverse=True)
    # master is still ranked by |rank_z| desc
    abs_z = res["master"]["abs_z"].dropna().tolist()
    assert abs_z == sorted(abs_z, reverse=True)
    # at least one idiosyncratic example present
    assert (res["master"]["dislocation_type"] == "IDIOSYNCRATIC").any()


# ----------------------------------------------------------------------------
# v2 tests
# ----------------------------------------------------------------------------

def test_rank_mode_max_abs_picks_larger_magnitude_signed():
    p = dict(se.DEFAULT_PARAMS)
    p["rank_mode"] = "max_abs"
    assert se._rank_z_from(0.5, -2.0, p) == -2.0
    assert se._rank_z_from(-3.0, 1.0, p) == -3.0
    assert se._rank_z_from(2.0, -2.0, p) == 2.0  # tie favors z_a (>=)
    assert se._rank_z_from(float("nan"), 1.5, p) == 1.5
    assert se._rank_z_from(0.7, float("nan"), p) == 0.7
    assert np.isnan(se._rank_z_from(float("nan"), float("nan"), p))


def test_rank_mode_horizon_a_uses_z_a_only():
    p = dict(se.DEFAULT_PARAMS)
    p["rank_mode"] = "horizon_a"
    assert se._rank_z_from(1.2, -9.0, p) == 1.2
    assert np.isnan(se._rank_z_from(float("nan"), -9.0, p))


def test_rank_mode_weighted_blends_and_renormalizes():
    p = dict(se.DEFAULT_PARAMS)
    p["rank_mode"] = "weighted"
    p["z_weight_a"] = 0.5
    p["z_weight_b"] = 0.5
    assert abs(se._rank_z_from(2.0, 4.0, p) - 3.0) < 1e-12
    assert se._rank_z_from(float("nan"), 4.0, p) == 4.0


def test_raw_vs_demean_z_formula():
    r, mu, sigma, h = 0.08, 0.002, 0.015, 5
    raw = se.volatility_normalized_z(r, mu, sigma, h)
    demeaned = se.volatility_normalized_z(r, mu, sigma, h, demean=True)
    assert abs(raw - r / (sigma * np.sqrt(h))) < 1e-12
    assert abs(demeaned - (r - mu * h) / (sigma * np.sqrt(h))) < 1e-12
    assert abs(raw - demeaned) > 1e-9


def test_peer_loo_excludes_self_and_solo():
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2024-01-01", periods=120)
    rows, uni = [], []
    specs = {
        "B1": ("Fin", "BankSub", -0.18),
        "B2": ("Fin", "BankSub", 0.0),
        "B3": ("Fin", "BankSub", 0.0),
        "B4": ("Fin", "BankSub", 0.0),
        "S1": ("Energy", "SolarSub", 0.30),
    }
    for t, (sec, sub, shock) in specs.items():
        rets = rng.normal(0.0002, 0.012, 120)
        if shock:
            rets[-7:] += (1 + shock) ** (1 / 7) - 1
        prices = 100.0 * np.cumprod(1 + rets)
        for d, pr in zip(dates, prices):
            rows.append({"ticker": t, "date": d, "close": float(pr), "volume": 1_000_000})
        uni.append({"ticker": t, "name": t, "sector": sec, "sub_industry": sub,
                    "index_weight": 1.0, "adv_usd_20d": 50_000_000, "below_floor": False})
    res = se.run_screen(pd.DataFrame(rows), pd.DataFrame(uni), se.DEFAULT_PARAMS)
    m = res["master"].set_index("ticker")
    assert m.loc["B1", "peer_group_used"] == "sub_industry"
    assert m.loc["B1", "peer_count"] == 3
    assert m.loc["B1", "peer_relative_z"] < -1.0
    assert m.loc["B1", "dislocation_type"] == "IDIOSYNCRATIC"
    assert m.loc["S1", "peer_group_used"] == "solo"
    assert m.loc["S1", "peer_count"] == 0
    assert m.loc["S1", "dislocation_type"] == "IDIOSYNCRATIC"


def test_peer_sector_rollup_when_sub_thin():
    rng = np.random.default_rng(11)
    dates = pd.bdate_range("2024-01-01", periods=120)
    rows, uni = [], []
    specs = {
        "T":  ("Tech", "SubA", -0.15),
        "P1": ("Tech", "SubB", 0.0),
        "P2": ("Tech", "SubC", 0.0),
        "P3": ("Tech", "SubD", 0.0),
    }
    for t, (sec, sub, shock) in specs.items():
        rets = rng.normal(0.0002, 0.012, 120)
        if shock:
            rets[-7:] += (1 + shock) ** (1 / 7) - 1
        prices = 100.0 * np.cumprod(1 + rets)
        for d, pr in zip(dates, prices):
            rows.append({"ticker": t, "date": d, "close": float(pr), "volume": 1_000_000})
        uni.append({"ticker": t, "name": t, "sector": sec, "sub_industry": sub,
                    "index_weight": 1.0, "adv_usd_20d": 50_000_000, "below_floor": False})
    res = se.run_screen(pd.DataFrame(rows), pd.DataFrame(uni), se.DEFAULT_PARAMS)
    m = res["master"].set_index("ticker")
    assert m.loc["T", "peer_group_used"] == "sector"
    assert m.loc["T", "peer_count"] == 3


def test_scored_playbook_selective_and_ranked():
    uni, prices = _synthetic_universe_and_prices()
    p = dict(se.DEFAULT_PARAMS, playbook_mode="scored")
    res = se.run_screen(prices, uni, p)
    os_df = res["oversold"]
    assert len(os_df) > 0
    scores = os_df["reversion_score"].tolist()
    assert scores == sorted(scores, reverse=True)
    assert len(os_df) < len(res["master"])
    assert (os_df["rank_z"] < 0).all()
    assert (os_df["reversion_score"] >= p["score_threshold"]).all()


def test_strict_mode_reproduces_hard_and():
    uni, prices = _synthetic_universe_and_prices()
    p = dict(se.DEFAULT_PARAMS, playbook_mode="strict")
    res = se.run_screen(prices, uni, p)
    zc = p["z_cutoff"]
    for r in res["oversold"].to_dict("records"):
        assert r["rank_z"] <= -zc
        assert r["dist_from_sma"] < 0
        assert r["rsi"] < p["rsi_oversold"]
    az = res["oversold"]["abs_z"].tolist()
    assert az == sorted(az, reverse=True)


def test_partial_history_excluded_from_playbooks_but_in_master():
    uni, prices = _synthetic_universe_and_prices()
    res = se.run_screen(prices, uni, se.DEFAULT_PARAMS)
    master = res["master"]
    ph_tickers = set(master[master["partial_history"]]["ticker"])
    if ph_tickers:
        assert ph_tickers.isdisjoint(set(res["oversold"]["ticker"]))
        assert ph_tickers.isdisjoint(set(res["overbought"]["ticker"]))
    # scoring works on a partial-history stub; membership mask excludes it
    df_stub = pd.DataFrame([
        {"rank_z": -2.0, "z_1w": -2.0, "z_1m_ex_week": float("nan"),
         "partial_history": True, "dist_from_sma": -1.0,
         "dist_from_sma_sigma": -2.0, "rsi": 20.0, "macd_state": "Bearish"},
    ])
    scored = se._compute_scores(df_stub, se.DEFAULT_PARAMS)
    assert scored["reversion_score"].iloc[0] >= 0


def test_unknown_adv_policy_flag_exclude_include():
    uni, prices = _synthetic_universe_and_prices()
    uni.loc[uni["ticker"] == "EEE", "adv_usd_20d"] = np.nan
    res_flag = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, unknown_adv_policy="flag"))
    mf = res_flag["master"].set_index("ticker")
    assert "EEE" in mf.index
    assert bool(mf.loc["EEE", "adv_unknown"]) is True
    res_excl = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, unknown_adv_policy="exclude"))
    assert "EEE" not in res_excl["master"]["ticker"].tolist()
    assert "EEE" in res_excl["skipped"]["ticker"].tolist()
    res_incl = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, unknown_adv_policy="include"))
    mi = res_incl["master"].set_index("ticker")
    assert "EEE" in mi.index
    assert bool(mi.loc["EEE", "adv_unknown"]) is True


def test_meta_asof_and_event_data_loaded():
    uni, prices = _synthetic_universe_and_prices()
    res = se.run_screen(prices, uni, se.DEFAULT_PARAMS)
    meta = res["meta"]
    assert meta["asof"] is not None
    assert meta["event_data_loaded"] is False
    asof = pd.to_datetime(prices["date"].max())
    uni2 = uni.copy()
    uni2["event_date"] = pd.Series([np.nan] * len(uni2), dtype=object)
    uni2.loc[uni2["ticker"] == "AAA", "event_date"] = (asof + pd.Timedelta(days=3)).date().isoformat()
    res2 = se.run_screen(prices, uni2, se.DEFAULT_PARAMS)
    assert res2["meta"]["event_data_loaded"] is True
    m2 = res2["master"].set_index("ticker")
    assert bool(m2.loc["AAA", "event_flag"]) is True


def test_days_stale_helper():
    asof = pd.Timestamp("2026-06-15")  # Monday
    assert se.days_stale(asof, today=asof) == 0
    assert se.days_stale(asof, today=pd.Timestamp("2026-06-18")) == 3  # Mon->Thu
    assert se.days_stale(asof, today=pd.Timestamp("2026-06-22")) == 5  # Mon->next Mon
    assert se.days_stale(None) is None


def test_rsi_defaults_are_35_65():
    assert se.DEFAULT_PARAMS["rsi_oversold"] == 35.0
    assert se.DEFAULT_PARAMS["rsi_overbought"] == 65.0


def test_z_columns_always_present_regardless_of_mode():
    uni, prices = _synthetic_universe_and_prices()
    for mode in ("max_abs", "weighted", "horizon_a"):
        res = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, rank_mode=mode))
        cols = res["master"].columns
        assert "z_1w" in cols and "z_1m_ex_week" in cols and "rank_z" in cols
