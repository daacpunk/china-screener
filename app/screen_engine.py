"""Pure, testable screening engine.

Implements the 4-step reversion/fade screen. No web/DB dependencies: takes a
tidy price/volume DataFrame plus a universe DataFrame and a params dict, returns
ranked result DataFrames. All math (z-scores, distance-from-mean, peer-relative
z, playbook classification) lives here so it can be unit-tested directly.

Inputs
------
prices: tidy DataFrame with columns: ticker, date, close, [volume]
universe: DataFrame with columns: ticker, name, sector, sub_industry,
          index_weight, [adv_usd_20d], [below_floor], [event_date]
params: dict of screen parameters (see DEFAULT_PARAMS).

Outputs
-------
dict with keys:
  'master'    -> all screened names with metrics, ranked by |composite z| desc
  'oversold'  -> oversold-reversion longs, ranked by |z| desc
  'overbought'-> overbought-fade shorts, ranked by |z| desc
  'skipped'   -> names dropped for too few bars / missing data (with reason)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from . import indicators as ind

DEFAULT_PARAMS: Dict[str, Any] = {
    # horizon windows in trading days
    "horizon_a_lookback": 5,        # 1-week return = last 5 td
    "horizon_b_start": 21,          # 1-month-ex-last-week: from day -21 ...
    "horizon_b_end": 5,             # ... to day -5 (non-overlapping with A)
    # trailing window for daily mean/vol estimation (configurable 20-60)
    "vol_window": 60,
    # indicators
    "rsi_length": 14,
    "rsi_oversold": 30.0,
    "rsi_overbought": 70.0,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "sma_length": 20,
    # z cutoffs for playbook membership (|z| threshold on composite)
    "z_cutoff": 1.0,
    # idiosyncratic divergence threshold
    "divergence_threshold": 1.0,
    # event window (days) — flag if event within N days
    "event_window_days": 7,
    # min bars for warm-up
    "min_bars": 60,
    # liquidity floor: 20D ADV USD must exceed this to be screenable
    "adv_floor": 10_000_000,
    # composite z weighting (Horizon A vs B). They are blended for ranking.
    "z_weight_a": 0.5,
    "z_weight_b": 0.5,
}


def _safe_float(x) -> float:
    try:
        v = float(x)
        return v
    except Exception:
        return float("nan")


def horizon_return(close: pd.Series, start_offset: int, end_offset: int) -> float:
    """Return over a non-overlapping window.

    Window is from price at index (-start_offset-1) to price at (-end_offset-1),
    i.e. return = P[-end_offset-1] / P[-start_offset-1] - 1.

    For Horizon A (1-week): start_offset=5, end_offset=0 -> last 5 td return.
    For Horizon B (1m-ex-week): start_offset=21, end_offset=5 -> day -21 to -5.
    """
    s = pd.Series(close).dropna().reset_index(drop=True)
    n = len(s)
    i_start = n - 1 - start_offset
    i_end = n - 1 - end_offset
    if i_start < 0 or i_end < 0 or i_start >= n or i_end >= n:
        return float("nan")
    p0 = s.iloc[i_start]
    p1 = s.iloc[i_end]
    if p0 == 0 or pd.isna(p0) or pd.isna(p1):
        return float("nan")
    return float(p1 / p0 - 1.0)


def volatility_normalized_z(
    realized_return: float,
    daily_mean: float,
    daily_vol: float,
    horizon: int,
) -> float:
    """z = (r_horizon - mu_daily*h) / (sigma_daily*sqrt(h))."""
    if any(pd.isna(v) for v in (realized_return, daily_mean, daily_vol)):
        return float("nan")
    denom = daily_vol * np.sqrt(horizon)
    if denom == 0 or pd.isna(denom):
        return float("nan")
    return float((realized_return - daily_mean * horizon) / denom)


def compute_name_metrics(
    g: pd.DataFrame, params: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Compute all per-name metrics for one ticker's sorted price frame.

    Returns None-like dict with 'skip_reason' if insufficient data.
    """
    g = g.sort_values("date").reset_index(drop=True)
    close = g["close"].astype("float64")
    n = int(close.notna().sum())
    min_bars = params["min_bars"]
    if n < min_bars:
        return {"skip_reason": f"too few bars ({n} < {min_bars})"}

    # indicators
    enr = ind.compute_indicators_for_series(
        g,
        rsi_length=params["rsi_length"],
        macd_fast=params["macd_fast"],
        macd_slow=params["macd_slow"],
        macd_signal=params["macd_signal"],
        sma_length=params["sma_length"],
    )
    last = enr.iloc[-1]
    rsi_val = _safe_float(last.get("rsi"))
    macd_val = _safe_float(last.get("macd"))
    macd_sig = _safe_float(last.get("macd_signal"))
    dist_sma = _safe_float(last.get("dist_from_sma"))

    # daily returns over trailing vol window
    rets = close.pct_change().dropna()
    vw = params["vol_window"]
    trailing = rets.tail(vw)
    daily_mean = _safe_float(trailing.mean())
    daily_vol = _safe_float(trailing.std(ddof=1))

    # distance-from-20d-mean in sigma units
    dist_sigma = float("nan")
    if not pd.isna(daily_vol) and daily_vol != 0 and not pd.isna(dist_sma):
        dist_sigma = dist_sma / daily_vol

    # horizon returns (non-overlapping)
    a_lb = params["horizon_a_lookback"]
    b_start = params["horizon_b_start"]
    b_end = params["horizon_b_end"]
    r_a = horizon_return(close, start_offset=a_lb, end_offset=0)
    r_b = horizon_return(close, start_offset=b_start, end_offset=b_end)
    h_a = a_lb
    h_b = b_start - b_end

    z_a = volatility_normalized_z(r_a, daily_mean, daily_vol, h_a)
    z_b = volatility_normalized_z(r_b, daily_mean, daily_vol, h_b)

    wa, wb = params["z_weight_a"], params["z_weight_b"]
    parts = [(z_a, wa), (z_b, wb)]
    valid = [(z, w) for z, w in parts if not pd.isna(z)]
    if valid:
        wsum = sum(w for _, w in valid)
        composite_z = sum(z * w for z, w in valid) / wsum if wsum else float("nan")
    else:
        composite_z = float("nan")

    return {
        "ret_1w": r_a,
        "ret_1m_ex_week": r_b,
        "z_1w": z_a,
        "z_1m_ex_week": z_b,
        "composite_z": composite_z,
        "rsi": rsi_val,
        "macd": macd_val,
        "macd_signal_val": macd_sig,
        "macd_state": ind.macd_state(macd_val, macd_sig),
        "dist_from_sma": dist_sma,
        "dist_from_sma_sigma": dist_sigma,
        "rsi_signal": ind.rsi_signal(
            rsi_val, params["rsi_oversold"], params["rsi_overbought"]
        ),
        "combined_signal": ind.combined_signal(
            rsi_val, macd_val, macd_sig, params["rsi_oversold"], params["rsi_overbought"]
        ),
        "n_bars": n,
        "skip_reason": None,
    }


def _event_flag(event_date, asof: pd.Timestamp, window_days: int) -> bool:
    if event_date is None or (isinstance(event_date, float) and pd.isna(event_date)):
        return False
    try:
        ed = pd.to_datetime(event_date)
    except Exception:
        return False
    if pd.isna(ed):
        return False
    delta = (ed - asof).days
    return 0 <= delta <= window_days


def run_screen(
    prices: pd.DataFrame,
    universe: pd.DataFrame,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, pd.DataFrame]:
    """Run the full Step1->Step4 screen. Pure function."""
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update({k: v for k, v in params.items() if v is not None})

    prices = prices.copy()
    prices.columns = [str(c).strip().lower() for c in prices.columns]
    if "close" not in prices.columns:
        for col in ["close", "price", "p_price", "adj close", "adj_close"]:
            if col in prices.columns:
                prices = prices.rename(columns={col: "close"})
                break
    if "ticker" not in prices.columns or "close" not in prices.columns or "date" not in prices.columns:
        raise ValueError("prices must contain ticker, date, close columns")
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna(subset=["date"])

    uni = universe.copy()
    uni.columns = [str(c).strip().lower() for c in uni.columns]
    # normalise expected universe columns
    rename_map = {
        "sub-industry": "sub_industry",
        "subindustry": "sub_industry",
        "gics_sub_industry": "sub_industry",
        "index weight": "index_weight",
        "weight": "index_weight",
        "20d_adv_usd": "adv_usd_20d",
        "adv_usd": "adv_usd_20d",
    }
    uni = uni.rename(columns={k: v for k, v in rename_map.items() if k in uni.columns})
    for col in ["name", "sector", "sub_industry", "index_weight", "adv_usd_20d", "below_floor", "event_date"]:
        if col not in uni.columns:
            uni[col] = np.nan

    asof = prices["date"].max()
    if pd.isna(asof):
        asof = pd.Timestamp(datetime.now(timezone.utc).date())

    rows = []
    skipped = []
    for tkr, g in prices.groupby("ticker"):
        urow = uni[uni["ticker"] == tkr]
        umeta = urow.iloc[0].to_dict() if len(urow) else {}
        metrics = compute_name_metrics(g, p)
        if metrics is None or metrics.get("skip_reason"):
            skipped.append({
                "ticker": tkr,
                "name": umeta.get("name"),
                "reason": (metrics or {}).get("skip_reason", "no metrics"),
            })
            continue
        below_floor = bool(umeta.get("below_floor")) if not pd.isna(umeta.get("below_floor", np.nan)) else False
        if below_floor:
            skipped.append({"ticker": tkr, "name": umeta.get("name"), "reason": "below liquidity floor"})
            continue
        row = {
            "ticker": tkr,
            "name": umeta.get("name"),
            "sector": umeta.get("sector"),
            "sub_industry": umeta.get("sub_industry"),
            "index_weight": _safe_float(umeta.get("index_weight")),
            "adv_usd_20d": _safe_float(umeta.get("adv_usd_20d")),
            "event_flag": _event_flag(umeta.get("event_date"), asof, p["event_window_days"]),
            "event_date": umeta.get("event_date"),
        }
        row.update(metrics)
        rows.append(row)

    cols = [
        "ticker", "name", "sector", "sub_industry", "index_weight", "adv_usd_20d",
        "ret_1w", "ret_1m_ex_week", "z_1w", "z_1m_ex_week", "composite_z",
        "dist_from_sma", "dist_from_sma_sigma", "rsi", "rsi_signal",
        "macd", "macd_signal_val", "macd_state", "combined_signal",
        "peer_relative_z", "dislocation_type", "event_flag", "event_date", "n_bars",
    ]
    if not rows:
        empty = pd.DataFrame(columns=cols)
        return {
            "master": empty,
            "oversold": empty.copy(),
            "overbought": empty.copy(),
            "skipped": pd.DataFrame(skipped),
        }

    df = pd.DataFrame(rows)

    # Step 3: idiosyncratic vs sector via sub-industry peer-relative z
    df["peer_relative_z"] = np.nan
    df["dislocation_type"] = "SECTOR/MACRO/POLICY"
    div = p["divergence_threshold"]
    for sub, grp in df.groupby("sub_industry", dropna=False):
        peer_z = grp["composite_z"].median(skipna=True)
        idx = grp.index
        df.loc[idx, "peer_relative_z"] = grp["composite_z"] - peer_z
    df["dislocation_type"] = np.where(
        df["peer_relative_z"].abs() >= div, "IDIOSYNCRATIC", "SECTOR/MACRO/POLICY"
    )

    # ranking helper
    df["abs_z"] = df["composite_z"].abs()

    # Step 4: playbooks
    zc = p["z_cutoff"]
    rsi_os = p["rsi_oversold"]
    rsi_ob = p["rsi_overbought"]

    oversold_mask = (
        (df["composite_z"] <= -zc)
        & (df["dist_from_sma"] < 0)
        & (df["rsi"] < rsi_os)
    )
    overbought_mask = (
        (df["composite_z"] >= zc)
        & (df["dist_from_sma"] > 0)
        & (df["rsi"] > rsi_ob)
    )

    oversold = df[oversold_mask].sort_values("abs_z", ascending=False).reset_index(drop=True)
    overbought = df[overbought_mask].sort_values("abs_z", ascending=False).reset_index(drop=True)
    master = df.sort_values("abs_z", ascending=False).reset_index(drop=True)

    keep = [c for c in cols if c in df.columns] + ["abs_z"]
    return {
        "master": master[keep],
        "oversold": oversold[keep],
        "overbought": overbought[keep],
        "skipped": pd.DataFrame(skipped) if skipped else pd.DataFrame(columns=["ticker", "name", "reason"]),
    }
