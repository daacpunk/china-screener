"""Phase D weekly quant metrics — PURE numpy/pandas, NaN-safe, never raises.

Consumes the snapshot dict produced by ``ingest.parse_weekly_workbook`` (or the
hydrated ``weekly_snapshots.data`` payload):

    {
      "asof": "YYYY-MM-DD" | None,
      "stale": bool, "n_stale": int | None,
      "tickers": {ticker: [{"date","close","volume"}, ...]},  # chronological
      "hsi": [{"date","close"}, ...],                          # chronological
      "partial": [ticker, ...],
      ...
    }

and returns a structured, JSON-serializable metrics dict:

    {
      "asof", "stale", "n_stale",
      "hsi": {ret_1w, ret_1m, ret_3m, ret_ytd, vol_20d, trend, n_bars, ...},
      "per_ticker": {ticker: {... all metrics ...}},
      "rows": [ {symbol/ticker + flat metrics}, ... ],   # tidy, for tables
      "movers": {gainers_1w, losers_1w, vol_shift, vola_shift,
                 rel_leaders, rel_laggards},
      "opportunities": {dislocations, relative_value, anomalies},
      "catalyst_names": [ticker, ...],   # top5 + bottom5 (+ outsized vol spike)
      "meta": {...},
    }

LOCKED metric definitions (client-friendly, simple):
  * Returns = simple % price change over the window (P_end/P_start - 1).
  * Windows: 1W = 5 trading days (headline); context 1M=21, 3M=63, 6M=126, YTD.
  * Volume trend = avg daily volume over the past week (last 5 td) vs trailing
    20D ADV -> ratio; ALSO the largest single-day volume spike in the week vs
    the 20D ADV.
  * Relative performance = stock window return MINUS HSI window return
    (headline 1W & YTD).
  * Momentum = trailing 1M & 3M return + risk-adjusted = 3M return / 20D
    annualized vol.
  * Volatility = annualized stdev of daily returns over 20 td (headline) and
    60 td (context), * sqrt(252); "elevated" when 20D vol clearly exceeds 60D.

Everything is computed in-app from the raw close/volume series. No formula here
ever raises: missing/short series yield ``None`` (JSON null) metrics.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import attribution as attrib

# Window lengths in trading days.
W_1W = 5
W_1M = 21
W_3M = 63
W_6M = 126
VOL_20 = 20
VOL_60 = 60
ADV_20 = 20
TRADING_DAYS = 252
ANN = math.sqrt(TRADING_DAYS)

# "elevated" volatility: 20D vol clearly exceeds 60D vol.
ELEVATED_RATIO = 1.25
# dislocation: |1W move| large AND |z vs own daily-return history| high.
DISLOCATION_RET = 0.08      # 8% absolute 1W move
DISLOCATION_Z = 2.0
# anomaly: big volume spike with a muted price move.
ANOMALY_VOL_RATIO = 2.0
ANOMALY_PRICE = 0.03        # |1W return| under 3%
# catalyst inclusion: outsized intra-week single-day volume spike.
OUTSIZED_SPIKE = 3.0
N_SIDE = 5                  # top5 gainers + bottom5 losers

# ----- Phase D-3 Wave 1 params -----
# Thin-liquidity caveat threshold (dollar 20D ADV below which a highlighted mover
# is flagged as harder to trade at size). LOCKED default $25m.
THIN_ADV_DOLLARS = 25_000_000
# Breadth advance/decline dead-band: names within +/- this 1W return count "flat".
BREADTH_FLAT = 0.001
# New-high / new-low detection tolerance: latest >= max*(1-tol) counts as a new
# high; latest <= min*(1+tol) counts as a new low.
NEW_EXTREME_TOL = 0.001
# Realized-beta estimation window + minimum overlapping observations, plus the
# sanity clip applied to the OLS slope.
BETA_WINDOW = 60
BETA_MIN_OBS = 40
BETA_CLIP_LOW = -3.0
BETA_CLIP_HIGH = 5.0
# Sector-rotation rank-change threshold for a "rotation in / out" tag.
ROTATION_RANK_DELTA = 3

# ----- Phase D-3 Wave 2 params: dispersion & correlation regime (#2) -----
# Correlation-regime thresholds on the average off-diagonal 20-day daily-return
# correlation across names. These are the PRIMARY classifier; dispersion is the
# tiebreaker (see ``regime_metrics``). Tunable defaults (LOCKED):
HIGH_CORR = 0.5     # avg pairwise corr at/above -> "macro-driven" leaning
LOW_CORR = 0.25     # avg pairwise corr at/below -> "idiosyncratic" leaning
# Correlation-matrix build controls: use the last N daily returns; a name needs
# at least MIN of those N aligned days to be included; need >= MIN_NAMES usable
# names for either statistic to be meaningful.
REGIME_CORR_WINDOW = 20
REGIME_CORR_MIN_DAYS = 15
REGIME_MIN_NAMES = 5
# Dispersion tiebreaker: rather than a fragile fixed % threshold, dispersion is
# classified RELATIVE to the observed cross-sectional dispersion using a simple
# scale anchor. A 1W cross-sectional stdev at/above this is "high" dispersion,
# at/below the low anchor is "low" dispersion. Defaults chosen for a weekly HSI
# tape (1W return stdev): ~3%+ across names is a wide, stock-picker's spread;
# <=1.5% is a tight, everything-moves-together spread.
REGIME_DISP_HIGH = 0.03
REGIME_DISP_LOW = 0.015

# Valuation-vs-sector descriptor thresholds (forward P/E vs BROAD-SECTOR median):
#   cheap  if fwd_pe <  CHEAP_MULT * sector_median
#   rich   if fwd_pe >  RICH_MULT  * sector_median
#   in line otherwise.
VAL_CHEAP_MULT = 0.85
VAL_RICH_MULT = 1.15
# A sector needs at least this many valid (positive) forward P/Es for its median
# to be a meaningful anchor.
MIN_SECTOR_PE = 2


def _f(x: Any) -> Optional[float]:
    """Coerce to a finite float, else None (JSON-safe)."""
    try:
        if x is None:
            return None
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def _series(records: List[Dict[str, Any]], field: str) -> pd.Series:
    """Build a chronological float Series indexed by date from snapshot records."""
    if not records:
        return pd.Series(dtype="float64")
    df = pd.DataFrame(records)
    if field not in df.columns or "date" not in df.columns:
        return pd.Series(dtype="float64")
    dt = pd.to_datetime(df["date"], errors="coerce")
    vals = pd.to_numeric(df[field], errors="coerce")
    s = pd.Series(vals.values, index=dt)
    s = s[~s.index.isna()].sort_index()
    return s.astype("float64")


def _window_return(close: pd.Series, n: int) -> Optional[float]:
    """Simple % return over the trailing ``n`` trading days (P_t / P_{t-n} - 1)."""
    c = close.dropna()
    if c.shape[0] < n + 1:
        return None
    p_end = c.iloc[-1]
    p_start = c.iloc[-1 - n]
    if p_start is None or p_start == 0 or not math.isfinite(p_start):
        return None
    return _f(p_end / p_start - 1.0)


def _ytd_return(close: pd.Series) -> Optional[float]:
    """Simple % return from the first available close of the latest calendar year
    (the last close on/before that year start) to the latest close."""
    c = close.dropna()
    if c.shape[0] < 2 or not isinstance(c.index, pd.DatetimeIndex):
        return None
    last_dt = c.index[-1]
    year_start = pd.Timestamp(year=last_dt.year, month=1, day=1)
    # Anchor = the last close strictly before the year start (prior year-end);
    # if none exists, use the first close of the year itself.
    prior = c[c.index < year_start]
    if prior.shape[0] >= 1:
        p_start = prior.iloc[-1]
    else:
        in_year = c[c.index >= year_start]
        if in_year.shape[0] < 2:
            return None
        p_start = in_year.iloc[0]
    p_end = c.iloc[-1]
    if p_start is None or p_start == 0 or not math.isfinite(p_start):
        return None
    return _f(p_end / p_start - 1.0)


def _ann_vol(close: pd.Series, n: int) -> Optional[float]:
    """Annualized stdev of daily simple returns over the trailing ``n`` td."""
    c = close.dropna()
    rets = c.pct_change().dropna()
    if rets.shape[0] < 2:
        return None
    tail = rets.tail(n)
    if tail.shape[0] < 2:
        return None
    sd = tail.std(ddof=1)
    if sd is None or not math.isfinite(sd):
        return None
    return _f(sd * ANN)


def _volume_trend(volume: pd.Series) -> Dict[str, Optional[float]]:
    """Past-week avg daily volume vs trailing 20D ADV (ratio), plus the largest
    single-day volume spike this week vs the 20D ADV."""
    v = volume.dropna()
    out: Dict[str, Optional[float]] = {
        "week_avg_vol": None, "adv_20d": None,
        "vol_ratio": None, "max_day_vol": None, "max_spike_ratio": None,
    }
    if v.shape[0] < 1:
        return out
    week = v.tail(W_1W)
    # 20D ADV measured over the bars just before this week where possible; if the
    # series is short, fall back to the trailing 20 across the whole series.
    if v.shape[0] >= W_1W + ADV_20:
        adv_base = v.iloc[-(W_1W + ADV_20):-W_1W]
    else:
        adv_base = v.tail(ADV_20)
    week_avg = _f(week.mean()) if week.shape[0] else None
    adv = _f(adv_base.mean()) if adv_base.shape[0] else None
    max_day = _f(week.max()) if week.shape[0] else None
    out["week_avg_vol"] = week_avg
    out["adv_20d"] = adv
    out["max_day_vol"] = max_day
    if adv and adv > 0:
        if week_avg is not None:
            out["vol_ratio"] = _f(week_avg / adv)
        if max_day is not None:
            out["max_spike_ratio"] = _f(max_day / adv)
    return out


def _dollar_liquidity(close: pd.Series, volume: pd.Series) -> Dict[str, Optional[float]]:
    """Dollar-liquidity metrics from the aligned close & volume series (#4).

    Builds a daily dollar-volume series (close * volume) over the shared dates and
    returns:
      * advv_20d          - mean daily dollar volume over the SAME trailing-20d
                            window used for the share-volume ADV (the 20 bars just
                            before this week when the series is long enough, else
                            the trailing 20 across whatever is available).
      * week_dollar_vol   - sum of daily dollar volume over the last 5 trading days.
      * dollar_spike_ratio- max single-day dollar volume in the last 5 td divided
                            by advv_20d (None when advv_20d is falsy).
    NaN-safe; never raises. Missing volume -> all None."""
    out: Dict[str, Optional[float]] = {
        "advv_20d": None, "week_dollar_vol": None, "dollar_spike_ratio": None,
    }
    c = close.dropna()
    v = volume.dropna()
    if c.shape[0] < 1 or v.shape[0] < 1:
        return out
    # Align close & volume on their shared dates, chronological.
    dv = (c * v).dropna()
    if dv.shape[0] < 1:
        return out
    dv = dv.sort_index()
    week = dv.tail(W_1W)
    if dv.shape[0] >= W_1W + ADV_20:
        adv_base = dv.iloc[-(W_1W + ADV_20):-W_1W]
    else:
        adv_base = dv.tail(ADV_20)
    advv = _f(adv_base.mean()) if adv_base.shape[0] else None
    week_sum = _f(week.sum()) if week.shape[0] else None
    week_max = _f(week.max()) if week.shape[0] else None
    out["advv_20d"] = advv
    out["week_dollar_vol"] = week_sum
    if advv and advv > 0 and week_max is not None:
        out["dollar_spike_ratio"] = _f(week_max / advv)
    return out


def realized_beta(stock_daily_returns: Any, hsi_daily_returns: Any) -> Optional[float]:
    """OLS slope (realized beta) of stock daily returns vs HSI daily returns (#3).

    Accepts pandas Series (date-indexed) or plain sequences of daily simple
    returns. When both are date-indexed Series they are ALIGNED by date and only
    the trailing ``BETA_WINDOW`` overlapping observations are used; needs at least
    ``BETA_MIN_OBS`` overlapping points. beta = cov(stock,hsi)/var(hsi) with a
    var>0 guard, clipped to [BETA_CLIP_LOW, BETA_CLIP_HIGH]. Returns None when
    inputs are too short / degenerate. Pure, NaN-safe, never raises."""
    try:
        s = stock_daily_returns
        h = hsi_daily_returns
        if isinstance(s, pd.Series) and isinstance(h, pd.Series):
            df = pd.concat([s.rename("s"), h.rename("h")], axis=1).dropna()
            df = df.tail(BETA_WINDOW)
            sv = df["s"].to_numpy(dtype="float64")
            hv = df["h"].to_numpy(dtype="float64")
        else:
            sv = np.asarray(list(s), dtype="float64")
            hv = np.asarray(list(h), dtype="float64")
            m = np.isfinite(sv) & np.isfinite(hv)
            sv, hv = sv[m], hv[m]
            if sv.shape[0] > BETA_WINDOW:
                sv = sv[-BETA_WINDOW:]
                hv = hv[-BETA_WINDOW:]
        if sv.shape[0] < BETA_MIN_OBS or hv.shape[0] < BETA_MIN_OBS:
            return None
        var = float(np.var(hv, ddof=1))
        if not math.isfinite(var) or var <= 0:
            return None
        cov = float(np.cov(sv, hv, ddof=1)[0, 1])
        beta = cov / var
        if not math.isfinite(beta):
            return None
        beta = max(BETA_CLIP_LOW, min(BETA_CLIP_HIGH, beta))
        return _f(beta)
    except Exception:  # noqa: BLE001 — pure module must never raise
        return None


def _return_z(close: pd.Series, ret_1w: Optional[float]) -> Optional[float]:
    """z-score of the 1W (5td) return vs the stock's own history of 5td returns."""
    if ret_1w is None:
        return None
    c = close.dropna()
    if c.shape[0] < W_1W + 5:
        return None
    roll = c.pct_change(W_1W).dropna()
    if roll.shape[0] < 5:
        return None
    mu = roll.mean()
    sd = roll.std(ddof=1)
    if sd is None or not math.isfinite(sd) or sd == 0:
        return None
    return _f((ret_1w - mu) / sd)


def _hsi_metrics(hsi_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    close = _series(hsi_records, "close")
    n = int(close.dropna().shape[0])
    r1w = _window_return(close, W_1W)
    r1m = _window_return(close, W_1M)
    r3m = _window_return(close, W_3M)
    rytd = _ytd_return(close)
    vol20 = _ann_vol(close, VOL_20)
    # short trend descriptor from the 1W & 1M moves.
    trend = _trend_descriptor(r1w, r1m)
    return {
        "ret_1w": r1w, "ret_1m": r1m, "ret_3m": r3m, "ret_ytd": rytd,
        "vol_20d": vol20, "trend": trend, "n_bars": n,
        "loaded": n > 0,
    }


def _trend_descriptor(r1w: Optional[float], r1m: Optional[float]) -> str:
    if r1w is None and r1m is None:
        return "n/a"
    s1w = 0.0 if r1w is None else r1w
    s1m = 0.0 if r1m is None else r1m
    if s1w > 0.005 and s1m > 0.005:
        return "uptrend"
    if s1w < -0.005 and s1m < -0.005:
        return "downtrend"
    if s1w > 0.005 and s1m <= 0.005:
        return "rebounding"
    if s1w < -0.005 and s1m >= -0.005:
        return "pulling back"
    return "range-bound"


# ---------------------------------------------------------------------------
# Fundamentals: valuation + earnings momentum (PURE, NaN-safe). Inputs are the
# point-in-time fundamental cells parsed by ingest (FE_ESTIMATE EPS consensus +
# GICS). Missing / n/a -> None; never raises.
# ---------------------------------------------------------------------------
def valuation_metrics(latest_close: Any, fundamentals: Dict[str, Any]
                      ) -> Dict[str, Any]:
    """Forward valuation P/E.

    PREFERS the FactSet-NATIVE next-twelve-month P/E pulled via
    FE_VALUATION(PE,MEAN,NTMA,..) (parsed as ``fwd_pe_ntm``) when it is present
    and positive. FALLS BACK to the in-app computation ``latest_close / FY1 EPS
    mean`` when the native field is missing/blank/non-positive.

    Returns {fwd_pe, fwd_pe_source, fwd_pe_ntm, fy1_eps_mean}:
      * fwd_pe        - the CHOSEN multiple (native or computed), or None.
      * fwd_pe_source - "factset" when the native field was used, "computed"
                        when the price/EPS fallback was used, None when neither
                        is available.
      * fwd_pe_ntm    - the raw native FE_VALUATION value (or None).
      * fy1_eps_mean  - the FY1 consensus EPS used by the fallback (or None).

    NaN-safe; never raises. A negative/zero forward multiple is suppressed
    (None) since it is not meaningful.
    """
    fnd = fundamentals or {}
    eps = _f(fnd.get("fy1_eps_mean"))
    px = _f(latest_close)
    ntm = _f(fnd.get("fwd_pe_ntm"))

    # Computed fallback (latest_close / FY1 EPS mean).
    computed = None
    if px is not None and eps is not None and eps > 0:
        computed = _f(px / eps)

    fwd_pe = None
    source = None
    if ntm is not None and ntm > 0:
        fwd_pe = ntm
        source = "factset"
    elif computed is not None:
        fwd_pe = computed
        source = "computed"

    return {
        "fwd_pe": fwd_pe,
        "fwd_pe_source": source,
        "fwd_pe_ntm": ntm,
        "fy1_eps_mean": eps,
    }


def earnings_momentum(fundamentals: Dict[str, Any]) -> Dict[str, Any]:
    """EPS estimate momentum / revisions, computed in-app from the FE_ESTIMATE
    snapshots (this is BOTH the 4-week revision look-back AND the EPS up/down
    backup):

      revision_abs = fy1 - fy1_4wk_ago
      revision_pct = revision_abs / |fy1_4wk_ago|   (None when base is 0/missing)
      revision_dir = sign -> "up" / "down" / "flat"
      dispersion   = stddev / |fy1|  (coefficient of variation) when both present
      num_est      = analyst coverage count
    """
    fnd = fundamentals or {}
    fy1 = _f(fnd.get("fy1_eps_mean"))
    fy2 = _f(fnd.get("fy2_eps_mean"))
    fy1_prev = _f(fnd.get("fy1_eps_mean_4wk_ago"))
    stddev = _f(fnd.get("fy1_eps_stddev"))
    num_est = _f(fnd.get("fy1_eps_num_est"))

    revision_abs = None
    revision_pct = None
    revision_dir = None
    if fy1 is not None and fy1_prev is not None:
        revision_abs = _f(fy1 - fy1_prev)
        if revision_abs is not None:
            if fy1_prev != 0:
                revision_pct = _f(revision_abs / abs(fy1_prev))
            # direction with a tiny dead-band to avoid float noise -> "flat".
            if abs(revision_abs) < 1e-9:
                revision_dir = "flat"
            elif revision_abs > 0:
                revision_dir = "up"
            else:
                revision_dir = "down"

    dispersion = None
    if stddev is not None and fy1 is not None and fy1 != 0:
        dispersion = _f(stddev / abs(fy1))

    return {
        "eps_fy1": fy1, "eps_fy2": fy2, "eps_fy1_4wk_ago": fy1_prev,
        "revision_abs": revision_abs, "revision_pct": revision_pct,
        "revision_dir": revision_dir, "dispersion": dispersion,
        "num_est": (int(num_est) if num_est is not None else None),
    }


def _sector_median_fwd_pe(rows: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Median forward P/E per BROAD FactSet sector (the full ``sector`` field, NOT
    the attribution peer group). Ignores None / non-positive P/Es. A sector with
    fewer than ``MIN_SECTOR_PE`` valid P/Es yields None (no reliable anchor).

    Returns {sector_label: median_fwd_pe | None}. NaN-safe; never raises."""
    by_sector: Dict[str, List[float]] = {}
    for r in rows:
        sec = r.get("sector")
        pe = _f(r.get("fwd_pe"))
        if not sec or pe is None or pe <= 0:
            continue
        by_sector.setdefault(str(sec).strip(), []).append(pe)
    out: Dict[str, Optional[float]] = {}
    for sec, pes in by_sector.items():
        if len(pes) >= MIN_SECTOR_PE:
            try:
                out[sec] = _f(float(np.median(pes)))
            except Exception:  # noqa: BLE001
                out[sec] = None
        else:
            out[sec] = None
    return out


def _valuation_vs_sector(fwd_pe: Optional[float],
                         sector_median: Optional[float]) -> Optional[str]:
    """"cheap" / "in line" / "rich" classification of a name's forward P/E vs its
    broad-sector median. None when either input is missing / non-positive."""
    pe = _f(fwd_pe)
    med = _f(sector_median)
    if pe is None or med is None or pe <= 0 or med <= 0:
        return None
    if pe < VAL_CHEAP_MULT * med:
        return "cheap"
    if pe > VAL_RICH_MULT * med:
        return "rich"
    return "in line"


def _ticker_metrics(
    records: List[Dict[str, Any]],
    symbol: str,
    hsi: Dict[str, Any],
    fundamentals: Optional[Dict[str, Any]] = None,
    sector_fallback: Optional[str] = None,
    hsi_returns: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    close = _series(records, "close")
    volume = _series(records, "volume")
    n = int(close.dropna().shape[0])

    r1w = _window_return(close, W_1W)
    r1m = _window_return(close, W_1M)
    r3m = _window_return(close, W_3M)
    r6m = _window_return(close, W_6M)
    rytd = _ytd_return(close)

    vol20 = _ann_vol(close, VOL_20)
    vol60 = _ann_vol(close, VOL_60)
    elevated = None
    if vol20 is not None and vol60 is not None and vol60 > 0:
        elevated = bool(vol20 >= ELEVATED_RATIO * vol60)

    vt = _volume_trend(volume)
    dl = _dollar_liquidity(close, volume)

    # HSI-relative (headline 1W & YTD): stock minus HSI over the same window.
    h1w = hsi.get("ret_1w")
    hytd = hsi.get("ret_ytd")
    rel_1w = _f(r1w - h1w) if (r1w is not None and h1w is not None) else None
    rel_ytd = _f(rytd - hytd) if (rytd is not None and hytd is not None) else None

    # ----- Beta-adjusted relative performance (#3) -----
    # Realized beta of the stock's daily returns vs the HSI daily returns over the
    # trailing 60 td; alpha_1w = ret_1w - beta * HSI 1W return. None when either
    # the beta or the required 1W returns are missing.
    beta_60d = None
    alpha_1w = None
    if hsi_returns is not None and hsi_returns.shape[0] >= BETA_MIN_OBS:
        stock_rets = close.dropna().pct_change().dropna()
        beta_60d = realized_beta(stock_rets, hsi_returns)
    if beta_60d is not None and r1w is not None and h1w is not None:
        alpha_1w = _f(r1w - beta_60d * h1w)

    # Momentum: 1M & 3M return + risk-adjusted = 3M return / 20D annualized vol.
    risk_adj_mom = None
    if r3m is not None and vol20 is not None and vol20 > 0:
        risk_adj_mom = _f(r3m / vol20)

    z_1w = _return_z(close, r1w)

    # ----- Fundamentals (point-in-time; absent old template -> all None) -----
    fnd = fundamentals or {}
    cc = close.dropna()
    latest_close = _f(cc.iloc[-1]) if cc.shape[0] else None
    valuation = valuation_metrics(latest_close, fnd)
    momentum = earnings_momentum(fnd)
    # FactSet classification: prefer the template pull, fall back to the
    # universe Sector column.
    sector = fnd.get("factset_sector") or sector_fallback or None
    sub_industry = fnd.get("factset_industry") or None
    company_name = fnd.get("company_name") or None
    business_desc = fnd.get("business_desc") or None
    has_fundamentals = any(v is not None for v in fnd.values()) if fnd else False

    return {
        "symbol": symbol,
        "n_bars": n,
        "ret_1w": r1w, "ret_1m": r1m, "ret_3m": r3m,
        "ret_6m": r6m, "ret_ytd": rytd,
        "rel_1w": rel_1w, "rel_ytd": rel_ytd,
        "vol_20d": vol20, "vol_60d": vol60, "vol_elevated": elevated,
        "week_avg_vol": vt["week_avg_vol"], "adv_20d": vt["adv_20d"],
        "vol_ratio": vt["vol_ratio"],
        "max_day_vol": vt["max_day_vol"], "max_spike_ratio": vt["max_spike_ratio"],
        "advv_20d": dl["advv_20d"], "week_dollar_vol": dl["week_dollar_vol"],
        "dollar_spike_ratio": dl["dollar_spike_ratio"],
        "beta_60d": beta_60d, "alpha_1w": alpha_1w,
        "mom_1m": r1m, "mom_3m": r3m, "risk_adj_mom": risk_adj_mom,
        "z_1w": z_1w,
        "latest_close": latest_close,
        "sector": sector, "sub_industry": sub_industry,
        "industry": sub_industry,
        "company_name": company_name, "business_desc": business_desc,
        "has_fundamentals": has_fundamentals,
        "fundamentals": (dict(fnd) if fnd else {}),
        "valuation": valuation,
        "momentum": momentum,
        "fwd_pe": valuation.get("fwd_pe"),
        "fwd_pe_source": valuation.get("fwd_pe_source"),
        # sector-anchor fields filled in a second pass once every name's P/E is
        # known (see compute_weekly_metrics).
        "sector_median_fwd_pe": None,
        "valuation_vs_sector": None,
        "eps_revision_dir": momentum.get("revision_dir"),
        "eps_revision_pct": momentum.get("revision_pct"),
        # 1W-return z vs the name's OWN trailing weekly-return distribution.
        # Exposed under both names so the note's "stretched to extremes"
        # watchlist can read ret_sigma directly.
        "ret_sigma": z_1w,
    }


# ---------------------------------------------------------------------------
# #1 Market breadth & internals (PURE, NaN-safe)
# ---------------------------------------------------------------------------
def breadth_metrics(
    per_ticker: Dict[str, Any],
    hsi_ret_1w: Optional[float] = None,
    new_highs: Optional[List[str]] = None,
    new_lows: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Advance/decline internals over the names with a valid 1W return (#1).

    Counts advancers (ret_1w > +BREADTH_FLAT), decliners (< -BREADTH_FLAT) and
    flat (between); breadth_ratio = adv/(adv+dec) (None when denom 0). Sums
    week_dollar_vol across advancing vs declining names (up/down dollar volume).
    New highs/lows are passed in (computed by the caller where the full price
    series is available). Compares breadth to the HSI 1W move to flag a narrow
    tape / hidden-strength divergence. Pure, NaN-safe, never raises."""
    per_ticker = per_ticker or {}
    adv = dec = flat = 0
    up_dv = 0.0
    down_dv = 0.0
    up_dv_seen = down_dv_seen = False
    for m in per_ticker.values():
        if not isinstance(m, dict):
            continue
        r = _f(m.get("ret_1w"))
        if r is None:
            continue
        dv = _f(m.get("week_dollar_vol"))
        if r > BREADTH_FLAT:
            adv += 1
            if dv is not None:
                up_dv += dv
                up_dv_seen = True
        elif r < -BREADTH_FLAT:
            dec += 1
            if dv is not None:
                down_dv += dv
                down_dv_seen = True
        else:
            flat += 1
    n_valid = adv + dec + flat
    denom = adv + dec
    breadth_ratio = _f(adv / denom) if denom > 0 else None

    divergence = None
    if breadth_ratio is not None and hsi_ret_1w is not None:
        h = _f(hsi_ret_1w)
        if h is not None:
            if h > 0.002 and breadth_ratio < 0.40:
                divergence = ("Narrow tape: index up but breadth negative \u2014 "
                              "gains concentrated in few names.")
            elif h < -0.002 and breadth_ratio > 0.60:
                divergence = ("Hidden strength: index down but most names "
                              "advanced.")
    return {
        "advancers": adv, "decliners": dec, "flat": flat, "n_valid": n_valid,
        "breadth_ratio": breadth_ratio,
        "new_highs": list(new_highs or []), "new_lows": list(new_lows or []),
        "up_dollar_vol": (_f(up_dv) if up_dv_seen else None),
        "down_dollar_vol": (_f(down_dv) if down_dv_seen else None),
        "divergence": divergence,
    }


# ---------------------------------------------------------------------------
# #6 Sector rotation scoreboard (PURE, NaN-safe)
# ---------------------------------------------------------------------------
def sector_rotation(
    per_ticker: Dict[str, Any],
    prev_sectors: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Group names by factset_sector; per sector compute median 1W & YTD return,
    count, and within-sector advancers/decliners; rank sectors by median 1W
    return descending (rank 1 = best) (#6).

    ``prev_sectors`` is the prior note's ``sector_rotation['sectors']`` list (same
    shape) or None. When present, each sector's prior rank is mapped and a
    rotation tag is set: "rotation in" when prev_rank - rank >= ROTATION_RANK_DELTA,
    "rotation out" when rank - prev_rank >= ROTATION_RANK_DELTA, else None.
    Returns {"sectors": [...], "note": "no history yet" | None}. Pure, NaN-safe,
    never raises."""
    per_ticker = per_ticker or {}
    groups: Dict[str, Dict[str, List[float]]] = {}
    for m in per_ticker.values():
        if not isinstance(m, dict):
            continue
        sec = m.get("sector")
        if not sec or not str(sec).strip():
            continue
        sec = str(sec).strip()
        g = groups.setdefault(sec, {"r1w": [], "rytd": []})
        r1w = _f(m.get("ret_1w"))
        rytd = _f(m.get("ret_ytd"))
        if r1w is not None:
            g["r1w"].append(r1w)
        if rytd is not None:
            g["rytd"].append(rytd)

    sectors: List[Dict[str, Any]] = []
    for sec, g in groups.items():
        r1w_list = g["r1w"]
        rytd_list = g["rytd"]
        med_1w = _f(float(np.median(r1w_list))) if r1w_list else None
        med_ytd = _f(float(np.median(rytd_list))) if rytd_list else None
        adv = sum(1 for x in r1w_list if x > BREADTH_FLAT)
        dec = sum(1 for x in r1w_list if x < -BREADTH_FLAT)
        sectors.append({
            "sector": sec, "ret_1w_med": med_1w, "ret_ytd_med": med_ytd,
            "n": len(r1w_list), "adv": adv, "dec": dec,
            "rank": None, "prev_rank": None, "rotation": None,
        })

    # Rank by median 1W return desc (rank 1 = best). Sectors with no valid median
    # sort to the bottom (stable).
    def _rank_key(s: Dict[str, Any]) -> float:
        v = s.get("ret_1w_med")
        return v if v is not None else float("-inf")
    sectors.sort(key=_rank_key, reverse=True)
    for i, s in enumerate(sectors, start=1):
        s["rank"] = i

    note: Optional[str] = None
    if prev_sectors:
        prev_rank_map: Dict[str, int] = {}
        for ps in prev_sectors:
            if not isinstance(ps, dict):
                continue
            name = ps.get("sector")
            pr = ps.get("rank")
            if name and pr is not None:
                try:
                    prev_rank_map[str(name).strip()] = int(pr)
                except (TypeError, ValueError):
                    continue
        for s in sectors:
            pr = prev_rank_map.get(s["sector"])
            s["prev_rank"] = pr
            if pr is not None:
                delta = pr - s["rank"]
                if delta >= ROTATION_RANK_DELTA:
                    s["rotation"] = "rotation in"
                elif -delta >= ROTATION_RANK_DELTA:
                    s["rotation"] = "rotation out"
    else:
        note = "no history yet"

    return {"sectors": sectors, "note": note}


# ---------------------------------------------------------------------------
# #2 Cross-sectional dispersion & correlation regime (PURE, NaN-safe)
# ---------------------------------------------------------------------------
REGIME_TAG_MACRO = "Macro-driven tape - alpha scarce, stock-picking harder"
REGIME_TAG_IDIO = "Idiosyncratic tape - stock-picking rewarded"
REGIME_TAG_MIXED = "Mixed tape"


def _regime_tag(avg_corr: Optional[float],
                dispersion: Optional[float]) -> str:
    """Classify the tape from average pairwise correlation (primary) and
    cross-sectional dispersion (tiebreaker). See ``regime_metrics`` docstring
    for the exact rule. Pure; never raises."""
    c = _f(avg_corr)
    d = _f(dispersion)
    if c is not None:
        # Correlation is the primary signal.
        if c >= HIGH_CORR:
            return REGIME_TAG_MACRO
        if c <= LOW_CORR:
            # Low correlation leans idiosyncratic, but require a genuinely wide
            # spread to CALL it idiosyncratic; a low-corr yet tight tape is mixed.
            if d is not None and d >= REGIME_DISP_HIGH:
                return REGIME_TAG_IDIO
            if d is not None and d <= REGIME_DISP_LOW:
                # low corr but everything barely moved -> not a stock-picker's
                # tape either; treat as macro-ish (nothing to pick).
                return REGIME_TAG_MACRO
            return REGIME_TAG_MIXED
        # Middle correlation band -> dispersion tiebreaker.
        if d is not None and d <= REGIME_DISP_LOW:
            return REGIME_TAG_MACRO
        if d is not None and d >= REGIME_DISP_HIGH:
            return REGIME_TAG_IDIO
        return REGIME_TAG_MIXED
    # No correlation available -> dispersion-only read.
    if d is not None:
        if d >= REGIME_DISP_HIGH:
            return REGIME_TAG_IDIO
        if d <= REGIME_DISP_LOW:
            return REGIME_TAG_MACRO
    return REGIME_TAG_MIXED


def regime_metrics(
    per_ticker: Dict[str, Any],
    daily_returns_by_ticker: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Cross-sectional dispersion + average pairwise correlation regime (#2).

    Two statistics, both NaN-safe (None when there is not enough data):

      * ``xsec_dispersion_1w`` \u2014 the SAMPLE standard deviation (ddof=1) of
        every valid 1W return across names. Requires >= REGIME_MIN_NAMES (5)
        valid 1W returns, else None. A wide spread = a stock-picker's tape.

      * ``avg_pairwise_corr_20d`` \u2014 the mean of the OFF-DIAGONAL entries
        (upper triangle, diagonal excluded) of the Pearson correlation matrix of
        the last ``REGIME_CORR_WINDOW`` (20) daily returns across names. Built
        from ``daily_returns_by_ticker`` (ticker -> date-indexed pandas Series
        of daily simple returns, as already computed for beta). Names are
        aligned on their common dates; a name is dropped when it has fewer than
        ``REGIME_CORR_MIN_DAYS`` (15) of the 20 aligned days. Requires >=
        REGIME_MIN_NAMES (5) usable names, else None. High = names move together
        (macro-driven); low = they move independently (idiosyncratic).

    Classification (``tag``) \u2014 correlation is PRIMARY, dispersion the
    tiebreaker; see ``_regime_tag``.

    Returns {"xsec_dispersion_1w", "avg_pairwise_corr_20d", "tag", "n_names"}
    where ``n_names`` is the number of names used in the correlation matrix (0
    when correlation could not be computed). Pure, NaN-safe, never raises.
    """
    try:
        per_ticker = per_ticker or {}
        daily_returns_by_ticker = daily_returns_by_ticker or {}

        # ----- Cross-sectional 1W dispersion (sample stdev, ddof=1) -----
        r1w_vals: List[float] = []
        for m in per_ticker.values():
            if not isinstance(m, dict):
                continue
            r = _f(m.get("ret_1w"))
            if r is not None:
                r1w_vals.append(r)
        dispersion: Optional[float] = None
        if len(r1w_vals) >= REGIME_MIN_NAMES:
            sd = float(np.std(np.asarray(r1w_vals, dtype="float64"), ddof=1))
            dispersion = _f(sd)

        # ----- Average pairwise 20D correlation -----
        avg_corr: Optional[float] = None
        n_names = 0
        series_map: Dict[str, pd.Series] = {}
        for tkr, rs in daily_returns_by_ticker.items():
            try:
                if isinstance(rs, pd.Series):
                    s = rs.dropna()
                else:
                    s = pd.Series(list(rs), dtype="float64").dropna()
            except Exception:  # noqa: BLE001
                continue
            if s.shape[0] >= 1:
                series_map[str(tkr)] = s
        if len(series_map) >= 2:
            try:
                mat = pd.concat(series_map, axis=1).sort_index()
                # Last 20 rows across the union of dates.
                mat = mat.tail(REGIME_CORR_WINDOW)
                # Drop names with < REGIME_CORR_MIN_DAYS non-NaN obs in window.
                counts = mat.count()
                keep = [c for c in mat.columns
                        if int(counts.get(c, 0)) >= REGIME_CORR_MIN_DAYS]
                mat = mat[keep]
                n_names = mat.shape[1]
                if n_names >= REGIME_MIN_NAMES:
                    # pandas .corr() is pairwise-complete + NaN-safe; average the
                    # upper triangle excluding the diagonal.
                    cm = mat.corr().to_numpy(dtype="float64")
                    k = cm.shape[0]
                    if k >= 2:
                        iu = np.triu_indices(k, k=1)
                        offdiag = cm[iu]
                        offdiag = offdiag[np.isfinite(offdiag)]
                        if offdiag.size >= 1:
                            avg_corr = _f(float(np.mean(offdiag)))
            except Exception:  # noqa: BLE001
                avg_corr = None

        tag = _regime_tag(avg_corr, dispersion)
        return {
            "xsec_dispersion_1w": dispersion,
            "avg_pairwise_corr_20d": avg_corr,
            "tag": tag,
            "n_names": int(n_names),
        }
    except Exception:  # noqa: BLE001 \u2014 pure module must never raise
        return {
            "xsec_dispersion_1w": None,
            "avg_pairwise_corr_20d": None,
            "tag": REGIME_TAG_MIXED,
            "n_names": 0,
        }


def _rank(rows: List[Dict[str, Any]], key: str, *, reverse: bool,
          n: int = N_SIDE, abs_val: bool = False) -> List[Dict[str, Any]]:
    """Top-``n`` rows by ``key`` (None values excluded). Stable, NaN-safe."""
    have = [r for r in rows if r.get(key) is not None]
    def sort_key(r: Dict[str, Any]) -> float:
        v = r[key]
        return abs(v) if abs_val else v
    have.sort(key=sort_key, reverse=reverse)
    return have[:n]


def _slim(r: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    base = {"symbol": r.get("symbol")}
    for k in keys:
        base[k] = r.get(k)
    return base


# Fields the note's grouped, plain-English movers section consumes for each
# entry. Attribution is attached later (post-attribution pass).
_MOVER_KEYS = (
    "company_name", "business_desc", "sector", "industry", "sub_industry",
    "ret_1w", "rel_1w", "vol_ratio", "max_spike_ratio",
    "fwd_pe", "sector_median_fwd_pe", "valuation_vs_sector",
    "eps_revision_dir", "eps_revision_pct",
    "ret_sigma", "z_1w",
    "advv_20d", "week_dollar_vol", "dollar_spike_ratio",
    "beta_60d", "alpha_1w",
)


def _mover_entry(r: Dict[str, Any]) -> Dict[str, Any]:
    """A richer mover record carrying everything the note needs to write a
    plain-English, grouped line: name, sector tag, attribution, valuation-vs-
    sector anchor, EPS revision, dispersion, num_est, and the own-history
    return sigma. Attribution + dispersion/num_est are filled here from the
    full per-ticker record."""
    base = _slim(r, *_MOVER_KEYS)
    mom = r.get("momentum") or {}
    base["dispersion"] = mom.get("dispersion")
    base["num_est"] = mom.get("num_est")
    base["attribution"] = r.get("attribution")  # may be None until attrib pass
    return base


def compute_weekly_metrics(
    snapshot: Dict[str, Any],
    universe_sectors: Optional[Dict[str, str]] = None,
    attribution_params: Optional[Dict[str, float]] = None,
    prev_note_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute all Phase D weekly metrics from a snapshot dict. Never raises.

    ``universe_sectors`` (optional) maps ticker -> sector from the universe's
    optional 3rd Sector column; used as a fallback when the template's
    FG_FACTSET_SECTOR pull is missing. ``attribution_params`` overrides the
    sector-vs-stock-specific bands (see ``attribution.PARAMS``).

    ``prev_note_metrics`` (optional) is the PREVIOUS saved weekly note's metrics
    dict; its ``sector_rotation['sectors']`` list is used to compute rotation
    tags (#6). None -> the scoreboard reports "no history yet".

    Backward compatible: an old price/volume-only snapshot has no
    ``fundamentals`` key, so valuation/momentum come back None and the rest of
    the report is unchanged.
    """
    snapshot = snapshot or {}
    tickers: Dict[str, List[Dict[str, Any]]] = snapshot.get("tickers") or {}
    hsi_records: List[Dict[str, Any]] = snapshot.get("hsi") or []
    fundamentals_all: Dict[str, Dict[str, Any]] = snapshot.get("fundamentals") or {}
    universe_sectors = universe_sectors or {}

    hsi = _hsi_metrics(hsi_records)
    # HSI daily-return series (for realized beta). Empty when HSI absent.
    hsi_close = _series(hsi_records, "close")
    hsi_returns = hsi_close.dropna().pct_change().dropna()
    if hsi_returns.shape[0] < 1:
        hsi_returns = None

    per_ticker: Dict[str, Dict[str, Any]] = {}
    rows: List[Dict[str, Any]] = []
    new_highs: List[str] = []
    new_lows: List[str] = []
    # Per-ticker daily simple-return Series (date-indexed), reused for the
    # correlation regime (#2). Computed once here so we do not rebuild the price
    # series a second time.
    daily_returns_by_ticker: Dict[str, pd.Series] = {}
    for tkr, recs in tickers.items():
        try:
            m = _ticker_metrics(
                recs, str(tkr), hsi,
                fundamentals=fundamentals_all.get(str(tkr)),
                sector_fallback=universe_sectors.get(str(tkr)),
                hsi_returns=hsi_returns,
            )
        except Exception:  # noqa: BLE001 — pure module must never raise
            m = {"symbol": str(tkr), "n_bars": 0}
        per_ticker[str(tkr)] = m
        rows.append(m)
        # Daily-return series for the regime correlation matrix (#2).
        try:
            dr = _series(recs, "close").dropna().pct_change().dropna()
            if dr.shape[0] >= 1:
                daily_returns_by_ticker[str(tkr)] = dr
        except Exception:  # noqa: BLE001
            pass
        # New high / low: latest close vs the name's own full-series max / min.
        try:
            cc = _series(recs, "close").dropna()
            if cc.shape[0] >= 2:
                latest = float(cc.iloc[-1])
                hi = float(cc.max())
                lo = float(cc.min())
                if hi > 0 and latest >= hi * (1.0 - NEW_EXTREME_TOL):
                    new_highs.append(str(tkr))
                elif lo > 0 and latest <= lo * (1.0 + NEW_EXTREME_TOL):
                    new_lows.append(str(tkr))
        except Exception:  # noqa: BLE001
            pass

    # ----- Valuation anchor: broad-sector median forward P/E -----
    # Group every name by its broad FactSet sector, compute the median fwd P/E
    # per sector, then attach the anchor + a cheap/in line/rich descriptor to
    # each name. NaN-safe; None when the sector lacks >=2 valid P/Es.
    sector_medians = _sector_median_fwd_pe(rows)
    for r in rows:
        sec = r.get("sector")
        med = sector_medians.get(str(sec).strip()) if sec else None
        r["sector_median_fwd_pe"] = med
        r["valuation_vs_sector"] = _valuation_vs_sector(r.get("fwd_pe"), med)

    # ----- Movers & shakers -----
    gainers_1w = _rank(rows, "ret_1w", reverse=True)
    losers_1w = _rank(rows, "ret_1w", reverse=False)
    vol_shift = _rank(rows, "vol_ratio", reverse=True)            # biggest volume jumps
    vola_shift = _rank(rows, "vol_20d", reverse=True)             # highest 20D vol
    rel_leaders = _rank(rows, "rel_1w", reverse=True)             # vs HSI, 1W
    rel_laggards = _rank(rows, "rel_1w", reverse=False)
    # "Stretched to extremes": largest |1W-return sigma| vs each name's OWN
    # trailing weekly-return history -> mean-reversion watchlist.
    extremes = _rank(rows, "ret_sigma", reverse=True, abs_val=True)
    # Beta-adjusted alpha leaders / laggards (#3): top/bottom 5 by alpha_1w.
    alpha_leaders = _rank(rows, "alpha_1w", reverse=True)
    alpha_laggards = _rank(rows, "alpha_1w", reverse=False)

    # ----- Opportunities / gaps -----
    dislocations: List[Dict[str, Any]] = []
    relative_value: List[Dict[str, Any]] = []
    anomalies: List[Dict[str, Any]] = []
    for r in rows:
        r1w = r.get("ret_1w")
        z = r.get("z_1w")
        # Dislocation: large 1W move + high |z| vs own history.
        if (r1w is not None and z is not None
                and abs(r1w) >= DISLOCATION_RET and abs(z) >= DISLOCATION_Z):
            dislocations.append(_slim(r, "ret_1w", "z_1w", "rel_1w"))
        # Relative-value: lagging HSI YTD + (low vol OR improving momentum).
        rel_ytd = r.get("rel_ytd")
        vol20 = r.get("vol_20d")
        mom_1m = r.get("mom_1m")
        improving = (mom_1m is not None and mom_1m > 0)
        low_vol = False
        if vol20 is not None and hsi.get("vol_20d") is not None:
            low_vol = vol20 <= hsi["vol_20d"]
        if rel_ytd is not None and rel_ytd < 0 and (low_vol or improving):
            relative_value.append(_slim(r, "rel_ytd", "vol_20d", "mom_1m", "ret_ytd"))
        # Anomaly: outsized volume spike with a muted price move; or vol regime break.
        spike = r.get("max_spike_ratio")
        vol_elevated = r.get("vol_elevated")
        if (spike is not None and spike >= ANOMALY_VOL_RATIO
                and r1w is not None and abs(r1w) < ANOMALY_PRICE):
            anomalies.append({**_slim(r, "max_spike_ratio", "ret_1w", "vol_ratio"),
                              "kind": "volume_no_move"})
        elif vol_elevated:
            anomalies.append({**_slim(r, "vol_20d", "vol_60d"),
                              "kind": "vol_regime_break"})

    # Rank opportunity lists by salience.
    dislocations.sort(key=lambda r: abs(r.get("z_1w") or 0.0), reverse=True)
    relative_value.sort(key=lambda r: (r.get("rel_ytd") or 0.0))
    anomalies.sort(key=lambda r: (r.get("max_spike_ratio") or r.get("vol_20d") or 0.0),
                   reverse=True)

    opportunities = {
        "dislocations": dislocations[:N_SIDE],
        "relative_value": relative_value[:N_SIDE],
        "anomalies": anomalies[:N_SIDE],
    }

    # ----- Catalyst names: top5 gainers + bottom5 losers (by 1W) plus any name
    # with an outsized intra-week single-day volume spike not already in the 10.
    catalyst: List[str] = []
    for r in gainers_1w + losers_1w:
        sym = r.get("symbol")
        if sym and sym not in catalyst:
            catalyst.append(sym)
    for r in rows:
        sym = r.get("symbol")
        spike = r.get("max_spike_ratio")
        if sym and sym not in catalyst and spike is not None and spike >= OUTSIZED_SPIKE:
            catalyst.append(sym)

    # ----- Sector-vs-stock-specific attribution for the notable movers -----
    # Peer groups are formed from the WHOLE universe (leave-one-out), then
    # attribution is computed for every notable mover (top5 gainers/bottom5
    # losers + the vol-shift, volatility and extremes movers). Reuses the
    # screen-engine leave-one-out peer-median logic via the weekly helper.
    mover_syms: List[str] = []
    for group in (gainers_1w, losers_1w, vol_shift, vola_shift, extremes):
        for r in group:
            sym = r.get("symbol")
            if sym and sym not in mover_syms:
                mover_syms.append(sym)
    attribution = attrib.attribute_movers(rows, mover_syms, attribution_params)
    # Surface the tag on each per_ticker record for easy downstream rendering.
    # Because ``rows`` and ``per_ticker`` share the SAME dict objects, this also
    # makes attribution visible to the rich mover entries built below.
    for sym, attr in attribution.items():
        if sym in per_ticker and isinstance(per_ticker[sym], dict):
            per_ticker[sym]["attribution"] = attr

    # Build the rich, note-ready movers AFTER attribution so each entry carries
    # its tag/peer-median/residual alongside name, sector, valuation anchor and
    # the own-history sigma.
    movers = {
        "gainers_1w": [_mover_entry(r) for r in gainers_1w],
        "losers_1w": [_mover_entry(r) for r in losers_1w],
        "vol_shift": [_mover_entry(r) for r in vol_shift],
        "vola_shift": [_slim(r, "vol_20d", "vol_60d", "vol_elevated",
                             "company_name", "sector") for r in vola_shift],
        "rel_leaders": [_mover_entry(r) for r in rel_leaders],
        "rel_laggards": [_mover_entry(r) for r in rel_laggards],
        "extremes": [_mover_entry(r) for r in extremes],
        "alpha_leaders": [_mover_entry(r) for r in alpha_leaders],
        "alpha_laggards": [_mover_entry(r) for r in alpha_laggards],
    }

    # ----- #1 Market breadth & internals + #6 Sector rotation scoreboard -----
    breadth = breadth_metrics(
        per_ticker, hsi_ret_1w=hsi.get("ret_1w"),
        new_highs=new_highs, new_lows=new_lows,
    )
    prev_sectors = None
    if prev_note_metrics:
        try:
            prev_sectors = ((prev_note_metrics.get("sector_rotation") or {})
                            .get("sectors"))
        except Exception:  # noqa: BLE001
            prev_sectors = None
    rotation = sector_rotation(per_ticker, prev_sectors)

    # ----- #2 Cross-sectional dispersion & correlation regime -----
    regime = regime_metrics(per_ticker, daily_returns_by_ticker)

    n_full = sum(1 for r in rows if (r.get("n_bars") or 0) >= W_3M)
    n_fund = sum(1 for r in rows if r.get("has_fundamentals"))
    n_fwd_pe = sum(1 for r in rows if r.get("fwd_pe") is not None)
    meta = {
        "n_tickers": len(rows),
        "n_full_history": n_full,
        "n_partial": len(snapshot.get("partial") or []),
        "hsi_loaded": hsi.get("loaded", False),
        "n_fundamentals": n_fund,
        "n_fwd_pe": n_fwd_pe,
        "fundamentals_loaded": n_fund > 0,
    }

    return {
        "asof": snapshot.get("asof"),
        "stale": snapshot.get("stale"),
        "n_stale": snapshot.get("n_stale"),
        "partial": snapshot.get("partial") or [],
        "hsi": hsi,
        "per_ticker": per_ticker,
        "rows": rows,
        "movers": movers,
        "opportunities": opportunities,
        "attribution": attribution,
        "catalyst_names": catalyst,
        "breadth": breadth,
        "sector_rotation": rotation,
        "regime": regime,
        "meta": meta,
    }
