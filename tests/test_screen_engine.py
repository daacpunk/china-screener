"""z-score math, non-overlapping window logic, peer-divergence tagging, demo flow."""
import numpy as np
import pandas as pd

from app import screen_engine as se


def test_volatility_normalized_z_formula():
    # z = (r - mu*h) / (sigma*sqrt(h))
    r, mu, sigma, h = 0.10, 0.001, 0.02, 5
    expected = (r - mu * h) / (sigma * np.sqrt(h))
    got = se.volatility_normalized_z(r, mu, sigma, h)
    assert abs(got - expected) < 1e-12


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


def test_demo_flow_non_empty_lists():
    """Acceptance #3: demo data -> both playbooks non-empty and ranked by |z|."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prices = pd.read_csv(os.path.join(here, "sample_data", "prices_sample.csv"))
    uni = pd.read_csv(os.path.join(here, "sample_data", "universe_sample.csv"))
    uni["below_floor"] = uni["20D_ADV_USD"] < 10_000_000
    res = se.run_screen(prices, uni, se.DEFAULT_PARAMS)
    assert len(res["oversold"]) > 0, "oversold-reversion list must be non-empty in demo"
    assert len(res["overbought"]) > 0, "overbought-fade list must be non-empty in demo"
    # ranked by |z|
    for key in ("oversold", "overbought"):
        z = res[key]["abs_z"].tolist()
        assert z == sorted(z, reverse=True)
    # at least one idiosyncratic example present
    assert (res["master"]["dislocation_type"] == "IDIOSYNCRATIC").any()
