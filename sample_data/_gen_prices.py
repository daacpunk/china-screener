"""Generate the synthetic ~250-day multi-ticker price/volume series.

Engineered so that:
  - Several names are clearly OVERSOLD (RSI<30, sharp recent drop, neg z).
  - Several names are clearly OVERBOUGHT (RSI>70, sharp rally, pos z).
  - At least one IDIOSYNCRATIC name diverges from its sub-industry peers.

Run from project root:  python sample_data/_gen_prices.py
Writes sample_data/prices_sample.csv
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

N_DAYS = 252
START = pd.Timestamp("2025-01-02")
rng = np.random.default_rng(20260618)


def business_dates(n):
    return pd.bdate_range(START, periods=n)


def make_series(base, drift_daily, vol_daily, n=N_DAYS, shock=None):
    """Geometric random walk; shock = (start_idx, end_idx, total_return)."""
    rets = rng.normal(drift_daily, vol_daily, n)
    if shock is not None:
        s, e, total = shock
        days = e - s
        per = (1 + total) ** (1.0 / days) - 1.0
        rets[s:e] += per
    prices = base * np.cumprod(1 + rets)
    return prices


# Define each ticker's regime. Sub-industries matter for peer-relative z.
# Internet Retail peers: BABA, PDD, JD ; Interactive Media: TCEHY, NTES, BIDU
# Diversified Banks: CCB, ICBC ; etc.
specs = {
    # OVERSOLD names: sharp recent drop in last ~5-10 days
    "BABA-CN": dict(base=95, drift=0.0002, vol=0.018, shock=(N_DAYS-8, N_DAYS, -0.26)),
    "JD-CN":   dict(base=40, drift=0.0001, vol=0.020, shock=(N_DAYS-7, N_DAYS, -0.24)),
    "SMIC-CN": dict(base=22, drift=0.0000, vol=0.022, shock=(N_DAYS-9, N_DAYS, -0.30)),
    # OVERBOUGHT names: sharp recent rally
    "PDD-CN":  dict(base=110, drift=0.0003, vol=0.020, shock=(N_DAYS-8, N_DAYS, 0.30)),
    "CATL-CN": dict(base=180, drift=0.0004, vol=0.021, shock=(N_DAYS-7, N_DAYS, 0.28)),
    "NTES-CN": dict(base=95, drift=0.0002, vol=0.018, shock=(N_DAYS-9, N_DAYS, 0.26)),
    # IDIOSYNCRATIC: TCEHY rallies hard while its peers (NTES up, BIDU flat) -
    # actually we want one name diverging from a calm peer group. Use BIDU
    # crashing while peers TCEHY/NTES are NOT crashing -> idiosyncratic oversold.
    "BIDU-CN": dict(base=130, drift=0.0001, vol=0.017, shock=(N_DAYS-8, N_DAYS, -0.32)),
    # Calm / neutral names
    "TCEHY-CN": dict(base=380, drift=0.0003, vol=0.014),
    "CCB-CN":   dict(base=6.5, drift=0.0001, vol=0.010),
    "ICBC-CN":  dict(base=5.2, drift=0.0001, vol=0.010),
    "PINGAN-CN":dict(base=48, drift=0.0001, vol=0.013),
    "LONGI-CN": dict(base=24, drift=-0.0001, vol=0.020),
    "NANO-CN":  dict(base=3.0, drift=0.0000, vol=0.030),  # below floor
}

dates = business_dates(N_DAYS)
rows = []
for tkr, sp in specs.items():
    prices = make_series(sp["base"], sp["drift"], sp["vol"], shock=sp.get("shock"))
    base_vol = rng.integers(2_000_000, 8_000_000)
    vols = (base_vol * (1 + rng.normal(0, 0.15, N_DAYS))).clip(min=10000).astype(int)
    # bump volume on shock days
    if sp.get("shock"):
        s, e, _ = sp["shock"]
        vols[s:e] = (vols[s:e] * 2.2).astype(int)
    for d, p, v in zip(dates, prices, vols):
        rows.append({"ticker": tkr, "date": d.date().isoformat(), "close": round(float(p), 4), "volume": int(v)})

df = pd.DataFrame(rows)
out = os.path.join(HERE, "prices_sample.csv")
df.to_csv(out, index=False)
print("wrote", out, "rows", len(df), "tickers", df.ticker.nunique())
