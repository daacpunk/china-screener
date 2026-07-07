"""Pure, testable screening engine (v2).

Implements the reversion/fade screen. No web/DB dependencies: takes a tidy
price/volume DataFrame plus a universe DataFrame and a params dict, returns
ranked result DataFrames. All math (z-scores, distance-from-mean, peer-relative
z, playbook classification) lives here so it can be unit-tested directly.

v2 changes (see SCREEN_V2_SPEC.md):
  1. rank_mode (default "max_abs"): a signed `rank_z` chosen by the larger-|z|
     horizon (preserving sign); also "weighted" and "horizon_a". Master and
     playbooks rank by abs(rank_z). z_1w / z_1m_ex_week always retained.
  2. z normalization RAW by default: z = r/(sigma*sqrt(h)); `demean` toggle
     (default False) restores (r - mu*h)/(sigma*sqrt(h)).
  3. Peer-relative z: leave-one-out median EXCLUDING self, with sub-industry ->
     sector roll-up and a solo IDIOSYNCRATIC tag; adds peer_group_used,
     peer_count.
  4. Scored playbooks (default) via reversion_score/fade_score + score_threshold;
     strict-AND opt-in via playbook_mode="strict". RSI defaults 35/65. Both
     horizons must be present for playbook entry.
  5. partial_history flag: z_a or z_b NaN -> stays in master (tagged), excluded
     from playbooks.
  6. unknown_adv_policy (default "flag"): adv_unknown names stay screenable and
     badged ("flag"); "exclude" drops them; "include" silent. adv_unknown column.
  7. run_screen returns asof in result["meta"]["asof"]; staleness handled by the
     route via days_stale() helper.
  8. event_date carried through; result["meta"]["event_data_loaded"] reflects
     whether any screened name has a populated event date.

Inputs
------
prices: tidy DataFrame with columns: ticker, date, close, [volume]
universe: DataFrame with columns: ticker, name, sector, sub_industry,
          index_weight, [adv_usd_20d], [below_floor], [adv_unknown], [event_date]
params: dict of screen parameters (see DEFAULT_PARAMS).

Outputs
-------
dict with keys:
  'master'    -> all screened names with metrics, ranked by abs(rank_z) desc
  'oversold'  -> oversold-reversion longs (scored or strict)
  'overbought'-> overbought-fade shorts (scored or strict)
  'skipped'   -> names dropped for too few bars / missing data (with reason)
  'meta'      -> dict: asof, event_data_loaded, n_idiosyncratic, n_sector, etc.
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
    "rsi_oversold": 35.0,           # v2: was 30
    "rsi_overbought": 65.0,         # v2: was 70
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "sma_length": 20,
    # z cutoffs for playbook membership (|z| threshold on rank_z; strict mode)
    "z_cutoff": 1.0,
    # idiosyncratic divergence threshold
    "divergence_threshold": 1.0,
    # event window (days) — flag if event within N days
    "event_window_days": 7,
    # min bars for warm-up
    "min_bars": 60,
    # liquidity floor: 20D ADV USD must exceed this to be screenable
    "adv_floor": 10_000_000,
    # composite z weighting (Horizon A vs B), used only in rank_mode="weighted"
    "z_weight_a": 0.5,
    "z_weight_b": 0.5,
    # --- v2 params ---
    # ranking metric: "max_abs" (default) | "weighted" | "horizon_a"
    "rank_mode": "max_abs",
    # z normalization: demean=False -> raw z = r/(sigma*sqrt(h)) (default)
    "demean": False,
    # peer classification minimum OTHER names to use a peer group
    "min_peers": 3,
    # playbook membership: "scored" (default) | "strict"
    "playbook_mode": "scored",
    # scored-playbook gate on the normalized 0..1-ish score
    "score_threshold": 0.5,
    # reversion/fade score weights (documented; normalized inputs in 0..1)
    "score_w_z": 0.5,       # weight on the rank-z magnitude term
    "score_w_dist": 0.3,    # weight on distance-from-SMA (sigma) magnitude
    "score_w_rsi": 0.2,     # weight on RSI extremity term
    "score_macd_bonus": 0.1,  # confirmation bonus when MACD agrees
    # liquidity: unknown-ADV policy: "flag" (default) | "exclude" | "include"
    "unknown_adv_policy": "flag",
    # data staleness warning threshold (days) — consumed at the route level
    "staleness_days": 3,
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
    demean: bool = False,
) -> float:
    """Volatility-normalized horizon z-score.

    If ``demean`` (legacy behavior): z = (r_horizon - mu_daily*h)/(sigma*sqrt(h)).
    Else (v2 default, RAW): z = r_horizon / (sigma_daily*sqrt(h)). Raw avoids
    pulling trending names toward zero by subtracting their drift.
    """
    needed = (realized_return, daily_vol) if not demean else (realized_return, daily_mean, daily_vol)
    if any(pd.isna(v) for v in needed):
        return float("nan")
    denom = daily_vol * np.sqrt(horizon)
    if denom == 0 or pd.isna(denom):
        return float("nan")
    numer = realized_return - (daily_mean * horizon if demean else 0.0)
    return float(numer / denom)


def _rank_z_from(z_a: float, z_b: float, params: Dict[str, Any]) -> float:
    """Compute the signed ranking z per `rank_mode`.

    - "max_abs": whichever of z_a/z_b has the larger magnitude, preserving sign.
      If one is NaN use the other; both NaN -> NaN.
    - "horizon_a": z_a only (z_b is confirmation).
    - "weighted": weighted blend with renormalize-when-NaN.
    """
    mode = params.get("rank_mode", "max_abs")
    a_na = pd.isna(z_a)
    b_na = pd.isna(z_b)
    if mode == "horizon_a":
        return float(z_a) if not a_na else float("nan")
    if mode == "weighted":
        wa, wb = params.get("z_weight_a", 0.5), params.get("z_weight_b", 0.5)
        parts = [(z_a, wa), (z_b, wb)]
        valid = [(z, w) for z, w in parts if not pd.isna(z)]
        if not valid:
            return float("nan")
        wsum = sum(w for _, w in valid)
        return float(sum(z * w for z, w in valid) / wsum) if wsum else float("nan")
    # default: max_abs
    if a_na and b_na:
        return float("nan")
    if a_na:
        return float(z_b)
    if b_na:
        return float(z_a)
    return float(z_a) if abs(z_a) >= abs(z_b) else float(z_b)


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

    demean = bool(params.get("demean", False))
    z_a = volatility_normalized_z(r_a, daily_mean, daily_vol, h_a, demean=demean)
    z_b = volatility_normalized_z(r_b, daily_mean, daily_vol, h_b, demean=demean)

    # ranking z (signed) per rank_mode
    rank_z = _rank_z_from(z_a, z_b, params)

    # composite z only meaningful in weighted mode; else mirror rank_z value of
    # the weighted blend for reference (kept available, not used for ranking).
    wa, wb = params["z_weight_a"], params["z_weight_b"]
    parts = [(z_a, wa), (z_b, wb)]
    valid = [(z, w) for z, w in parts if not pd.isna(z)]
    if valid:
        wsum = sum(w for _, w in valid)
        composite_z = sum(z * w for z, w in valid) / wsum if wsum else float("nan")
    else:
        composite_z = float("nan")

    partial_history = bool(pd.isna(z_a) or pd.isna(z_b))

    return {
        "ret_1w": r_a,
        "ret_1m_ex_week": r_b,
        "z_1w": z_a,
        "z_1m_ex_week": z_b,
        "rank_z": rank_z,
        "composite_z": composite_z,
        "partial_history": partial_history,
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


def _coerce_dt(v) -> Optional[pd.Timestamp]:
    """Coerce a value to a pd.Timestamp, or None if not parseable/blank.

    Robust to the raw shapes the two FactSet event pulls can arrive in even when
    they were NOT pre-decoded by ``data_ingest`` (e.g. a raw dump handed straight
    to ``run_screen``): an 8-digit ``YYYYMMDD`` calendar int/float/str (from
    ``FCA_EVENT_DATE(...,"YYYYMMDD")``) or an Excel/FactSet-Julian serial day.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "none", "nat"):
        return None
    # Numeric YYYYMMDD (e.g. 20260526 / 20260526.0) or Excel serial — decode
    # BEFORE the generic parser, which would read a bare int as nanoseconds.
    if not isinstance(v, (pd.Timestamp, datetime)):
        num = pd.to_numeric(s, errors="coerce")
        if pd.notna(num):
            n = float(num)
            iv = int(round(n))
            if 19000101 <= iv <= 99991231:
                ts = pd.to_datetime(str(iv), format="%Y%m%d", errors="coerce")
                if pd.notna(ts):
                    return ts
            if 20000 <= n <= 80000:
                ts = pd.to_datetime(n, unit="D", origin="1899-12-30",
                                    errors="coerce")
                if pd.notna(ts):
                    return ts
    try:
        ts = pd.to_datetime(v, errors="coerce")
    except Exception:
        return None
    return ts if pd.notna(ts) else None


def _select_event_date(ex_dividend_date, asof: pd.Timestamp,
                       window_days: int):
    """Decide whether the pulled EX-DIVIDEND date is an in-window event around
    ``asof``.

    Rule (reuses the existing ``event_window_days`` param as the half-window):
      * an EX-DIVIDEND date is mechanical the day the stock trades ex, so it is
        relevant when it falls within ``window_days`` on EITHER side of as-of
        (most-recent past ex-date or an imminent one).
    Ex-dividend is now the sole event-date source (the non-refreshing live
    earnings pulls were removed). Returns ``(event_date, in_window)``;
    ``event_date`` is the ex-dividend date (a Timestamp) or None when it does
    not parse, and ``in_window`` is True only when it falls inside the window.
    """
    ex = _coerce_dt(ex_dividend_date)
    if ex is None:
        return None, False
    try:
        w = int(window_days)
    except Exception:
        w = 7
    d = (ex - asof).days
    return ex, bool(abs(d) <= w)


def _has_event(event_date) -> bool:
    """True if a usable (parseable, non-null) event date is present."""
    if event_date is None or (isinstance(event_date, float) and pd.isna(event_date)):
        return False
    s = str(event_date).strip()
    if s == "" or s.lower() in ("nan", "none", "nat"):
        return False
    try:
        return not pd.isna(pd.to_datetime(event_date))
    except Exception:
        return False


def days_stale(asof, today: Optional[pd.Timestamp] = None) -> Optional[int]:
    """Business-day distance from ``asof`` to ``today`` (>=0), or None if unknown.

    Used by the Results/Data routes to decide whether to show a staleness banner.
    """
    if asof is None:
        return None
    try:
        a = pd.to_datetime(asof)
    except Exception:
        return None
    if pd.isna(a):
        return None
    t = pd.to_datetime(today) if today is not None else pd.Timestamp(datetime.now(timezone.utc).date())
    a = a.normalize()
    t = t.normalize()
    if t <= a:
        return 0
    # business-day count between a (exclusive) and t (inclusive)
    return int(np.busday_count(a.date(), t.date()))


def _minmax_norm(s: pd.Series) -> pd.Series:
    """Min-max normalize a non-negative magnitude series to 0..1 (robust to all-equal)."""
    s = s.astype("float64")
    lo = s.min(skipna=True)
    hi = s.max(skipna=True)
    if pd.isna(lo) or pd.isna(hi) or hi <= lo:
        # all equal / degenerate -> map present values to ~0.5, NaN stays NaN
        return s.where(s.isna(), 0.5)
    return (s - lo) / (hi - lo)


def _compute_scores(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """Add reversion_score and fade_score columns (normalized, documented).

    For OVERSOLD (reversion long, direction down): higher score = stronger
    reversion candidate. Built from normalized magnitudes:
        score = w_z*z_norm + w_dist*dist_norm + w_rsi*rsi_below_norm + macd_bonus
    where z_norm/dist_norm are min-max of the *downside* magnitudes, rsi_below
    rewards RSI under oversold, and the MACD bonus applies when MACD is bearish
    (confirming a still-falling name) — all clipped to 0..1.

    Fade is the symmetric mirror (upside magnitudes, RSI over overbought, MACD
    bullish bonus).
    """
    w_z = float(params.get("score_w_z", 0.5))
    w_dist = float(params.get("score_w_dist", 0.3))
    w_rsi = float(params.get("score_w_rsi", 0.2))
    macd_bonus = float(params.get("score_macd_bonus", 0.1))
    rsi_os = float(params.get("rsi_oversold", 35.0))
    rsi_ob = float(params.get("rsi_overbought", 65.0))

    rank_z = df["rank_z"].astype("float64")
    dist = df["dist_from_sma_sigma"].astype("float64")
    rsi = df["rsi"].astype("float64")
    macd_state = df["macd_state"].astype(str)

    # downside magnitudes (only negative side contributes)
    down_z = (-rank_z).clip(lower=0)
    down_dist = (-dist).clip(lower=0)
    # upside magnitudes
    up_z = rank_z.clip(lower=0)
    up_dist = dist.clip(lower=0)

    z_norm_down = _minmax_norm(down_z).fillna(0.0)
    dist_norm_down = _minmax_norm(down_dist).fillna(0.0)
    z_norm_up = _minmax_norm(up_z).fillna(0.0)
    dist_norm_up = _minmax_norm(up_dist).fillna(0.0)

    # RSI extremity terms in 0..1 (0 at the threshold, 1 at the extreme 0/100)
    rsi_below = ((rsi_os - rsi) / rsi_os).clip(lower=0, upper=1).fillna(0.0)
    rsi_above = ((rsi - rsi_ob) / (100.0 - rsi_ob)).clip(lower=0, upper=1).fillna(0.0)

    macd_bear = (macd_state == "Bearish").astype(float) * macd_bonus
    macd_bull = (macd_state == "Bullish").astype(float) * macd_bonus

    reversion = (w_z * z_norm_down + w_dist * dist_norm_down + w_rsi * rsi_below + macd_bear)
    fade = (w_z * z_norm_up + w_dist * dist_norm_up + w_rsi * rsi_above + macd_bull)

    df = df.copy()
    df["reversion_score"] = reversion.clip(lower=0, upper=1.0 + macd_bonus)
    df["fade_score"] = fade.clip(lower=0, upper=1.0 + macd_bonus)
    return df


def run_screen(
    prices: pd.DataFrame,
    universe: pd.DataFrame,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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

    # Company name pulled from the FactSet data dump (FG_COMPANY_NAME), if the
    # uploaded price file carried a 'name' column. Used as a FALLBACK when the
    # universe file itself lacks a name for a ticker. First non-blank per ticker.
    dump_name_map: Dict[str, str] = {}
    if "name" in prices.columns:
        for tkr, g in prices.groupby("ticker"):
            for v in g["name"].tolist():
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    s = str(v).strip()
                    if s and s.lower() not in ("nan", "none"):
                        dump_name_map[str(tkr).strip()] = s
                        break

    # Per-ticker ex-dividend event dates pulled from the FactSet data dump
    # (FCA_EVENT_DATE via =FDS). First non-null per ticker. This feeds
    # deterministic MECHANICAL_DISLOCATION tagging via _select_event_date below
    # and is now the SOLE event-date source (the non-refreshing live earnings
    # pulls were removed). Absent column -> empty map -> no events.
    def _first_dt_map(col: str) -> Dict[str, pd.Timestamp]:
        m: Dict[str, pd.Timestamp] = {}
        if col not in prices.columns:
            return m
        for tkr, g in prices.groupby("ticker"):
            for v in g[col].tolist():
                ts = _coerce_dt(v)
                if ts is not None:
                    m[str(tkr).strip()] = ts
                    break
        return m

    dump_exdiv_map = _first_dt_map("ex_dividend_date")

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
    for col in ["name", "sector", "sub_industry", "index_weight", "adv_usd_20d",
                "below_floor", "adv_unknown", "event_date"]:
        if col not in uni.columns:
            uni[col] = np.nan

    asof = prices["date"].max()
    if pd.isna(asof):
        asof = pd.Timestamp(datetime.now(timezone.utc).date())

    adv_policy = str(p.get("unknown_adv_policy", "flag")).lower()
    event_present_any = False

    rows = []
    skipped = []
    for tkr, g in prices.groupby("ticker"):
        urow = uni[uni["ticker"] == tkr]
        umeta = urow.iloc[0].to_dict() if len(urow) else {}

        # adv_unknown: ADV is NaN/blank in the universe
        adv_raw = umeta.get("adv_usd_20d", np.nan)
        adv_val = _safe_float(adv_raw)
        if "adv_unknown" in umeta and not pd.isna(umeta.get("adv_unknown", np.nan)):
            adv_unknown = bool(umeta.get("adv_unknown"))
        else:
            adv_unknown = bool(pd.isna(adv_val))

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
        # unknown-ADV policy
        if adv_unknown and adv_policy == "exclude":
            skipped.append({"ticker": tkr, "name": umeta.get("name"),
                            "reason": "ADV unknown (excluded by policy)"})
            continue

        # Event date: prefer a universe-supplied event_date (legacy path); else
        # derive it from the pulled FactSet ex-dividend date for this ticker
        # (the sole event-date source now).
        ev = umeta.get("event_date")
        tkr_key = str(tkr).strip()
        exdiv_dt = dump_exdiv_map.get(tkr_key)
        if _has_event(ev):
            # Legacy universe event_date wins; keep the original future-window rule.
            event_flag = _event_flag(ev, asof, p["event_window_days"])
            event_date_out = ev
            event_present_any = True
        elif exdiv_dt is not None:
            # Pulled ex-dividend date: flag when it is in-window around as-of.
            event_date_out, event_flag = _select_event_date(
                exdiv_dt, asof, p["event_window_days"])
            if _has_event(event_date_out):
                event_present_any = True
        else:
            event_flag = False
            event_date_out = ev  # blank/NaN -> unchanged, backward-compatible
        # Prefer the universe name; fall back to the data-dump name. Never
        # overwrite a good universe name with a blank.
        uni_name = umeta.get("name")
        if uni_name is None or (isinstance(uni_name, float) and pd.isna(uni_name)) \
                or str(uni_name).strip().lower() in ("", "nan", "none"):
            name_val = dump_name_map.get(str(tkr).strip())
        else:
            name_val = uni_name
        row = {
            "ticker": tkr,
            "name": name_val,
            "sector": umeta.get("sector"),
            "sub_industry": umeta.get("sub_industry"),
            "index_weight": _safe_float(umeta.get("index_weight")),
            "adv_usd_20d": adv_val,
            "adv_unknown": adv_unknown,
            "event_flag": bool(event_flag),
            "event_date": event_date_out,
        }
        row.update(metrics)
        rows.append(row)

    cols = [
        "ticker", "name", "sector", "sub_industry", "index_weight", "adv_usd_20d",
        "adv_unknown",
        "ret_1w", "ret_1m_ex_week", "z_1w", "z_1m_ex_week", "rank_z", "composite_z",
        "partial_history",
        "dist_from_sma", "dist_from_sma_sigma", "rsi", "rsi_signal",
        "macd", "macd_signal_val", "macd_state", "combined_signal",
        "peer_relative_z", "peer_group_used", "peer_count", "dislocation_type",
        "reversion_score", "fade_score",
        "event_flag", "event_date", "n_bars", "abs_z",
    ]
    meta = {
        "asof": (asof.date().isoformat() if isinstance(asof, pd.Timestamp) and not pd.isna(asof) else None),
        "event_data_loaded": bool(event_present_any),
        "n_idiosyncratic": 0,
        "n_sector": 0,
        "unknown_adv_policy": adv_policy,
        "rank_mode": p.get("rank_mode"),
        "playbook_mode": p.get("playbook_mode"),
        "staleness_days": int(p.get("staleness_days", 3)),
    }
    if not rows:
        empty = pd.DataFrame(columns=cols)
        return {
            "master": empty,
            "oversold": empty.copy(),
            "overbought": empty.copy(),
            "skipped": pd.DataFrame(skipped) if skipped else pd.DataFrame(columns=["ticker", "name", "reason"]),
            "meta": meta,
        }

    df = pd.DataFrame(rows)

    # Step 3: peer-relative z via leave-one-out median, sub-industry -> sector
    # roll-up -> solo. Uses rank_z (the chosen ranking z), not composite.
    min_peers = int(p.get("min_peers", 3))
    div = p["divergence_threshold"]
    df["peer_relative_z"] = np.nan
    df["peer_group_used"] = "solo"
    df["peer_count"] = 0

    rank_by_sub: Dict[Any, pd.Series] = {}
    rank_by_sec: Dict[Any, pd.Series] = {}
    for sub, grp in df.groupby("sub_industry", dropna=False):
        rank_by_sub[sub] = grp["rank_z"]
    for sec, grp in df.groupby("sector", dropna=False):
        rank_by_sec[sec] = grp["rank_z"]

    for idx, row in df.iterrows():
        rz = row["rank_z"]
        sub = row["sub_industry"]
        sec = row["sector"]
        # sub-industry leave-one-out
        sub_series = rank_by_sub.get(sub)
        peers_sub = sub_series.drop(idx) if sub_series is not None else pd.Series(dtype="float64")
        peers_sub = peers_sub.dropna()
        if len(peers_sub) >= min_peers:
            peer_z = float(peers_sub.median())
            df.at[idx, "peer_group_used"] = "sub_industry"
            df.at[idx, "peer_count"] = int(len(peers_sub))
            df.at[idx, "peer_relative_z"] = (rz - peer_z) if not pd.isna(rz) else np.nan
            continue
        # sector leave-one-out
        sec_series = rank_by_sec.get(sec)
        peers_sec = sec_series.drop(idx) if sec_series is not None else pd.Series(dtype="float64")
        peers_sec = peers_sec.dropna()
        if len(peers_sec) >= min_peers:
            peer_z = float(peers_sec.median())
            df.at[idx, "peer_group_used"] = "sector"
            df.at[idx, "peer_count"] = int(len(peers_sec))
            df.at[idx, "peer_relative_z"] = (rz - peer_z) if not pd.isna(rz) else np.nan
            continue
        # solo
        df.at[idx, "peer_group_used"] = "solo"
        df.at[idx, "peer_count"] = 0
        df.at[idx, "peer_relative_z"] = rz  # nothing to net against

    is_solo = df["peer_group_used"] == "solo"
    df["dislocation_type"] = np.where(
        is_solo | (df["peer_relative_z"].abs() >= div),
        "IDIOSYNCRATIC", "SECTOR/MACRO/POLICY",
    )

    # ranking helper
    df["abs_z"] = df["rank_z"].abs()

    # scores
    df = _compute_scores(df, p)

    # Step 4: playbooks
    mode = str(p.get("playbook_mode", "scored")).lower()
    rsi_os = p["rsi_oversold"]
    rsi_ob = p["rsi_overbought"]
    both_present = ~df["partial_history"].astype(bool)

    if mode == "strict":
        zc = p["z_cutoff"]
        oversold_mask = (
            both_present
            & (df["rank_z"] <= -zc)
            & (df["dist_from_sma"] < 0)
            & (df["rsi"] < rsi_os)
        )
        overbought_mask = (
            both_present
            & (df["rank_z"] >= zc)
            & (df["dist_from_sma"] > 0)
            & (df["rsi"] > rsi_ob)
        )
        oversold = df[oversold_mask].sort_values("abs_z", ascending=False).reset_index(drop=True)
        overbought = df[overbought_mask].sort_values("abs_z", ascending=False).reset_index(drop=True)
    else:  # scored
        thr = float(p.get("score_threshold", 0.5))
        oversold_mask = (
            both_present
            & (df["rank_z"] < 0)
            & (df["reversion_score"] >= thr)
        )
        overbought_mask = (
            both_present
            & (df["rank_z"] > 0)
            & (df["fade_score"] >= thr)
        )
        oversold = df[oversold_mask].sort_values("reversion_score", ascending=False).reset_index(drop=True)
        overbought = df[overbought_mask].sort_values("fade_score", ascending=False).reset_index(drop=True)

    master = df.sort_values("abs_z", ascending=False).reset_index(drop=True)

    meta["n_idiosyncratic"] = int((df["dislocation_type"] == "IDIOSYNCRATIC").sum())
    meta["n_sector"] = int((df["dislocation_type"] == "SECTOR/MACRO/POLICY").sum())
    meta["n_partial_history"] = int(df["partial_history"].astype(bool).sum())
    meta["n_adv_unknown"] = int(df["adv_unknown"].astype(bool).sum())

    keep = [c for c in cols if c in df.columns]
    return {
        "master": master[keep],
        "oversold": oversold[keep],
        "overbought": overbought[keep],
        "skipped": pd.DataFrame(skipped) if skipped else pd.DataFrame(columns=["ticker", "name", "reason"]),
        "meta": meta,
    }
