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

    # HSI-relative (headline 1W & YTD): stock minus HSI over the same window.
    h1w = hsi.get("ret_1w")
    hytd = hsi.get("ret_ytd")
    rel_1w = _f(r1w - h1w) if (r1w is not None and h1w is not None) else None
    rel_ytd = _f(rytd - hytd) if (rytd is not None and hytd is not None) else None

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
) -> Dict[str, Any]:
    """Compute all Phase D weekly metrics from a snapshot dict. Never raises.

    ``universe_sectors`` (optional) maps ticker -> sector from the universe's
    optional 3rd Sector column; used as a fallback when the template's
    FG_FACTSET_SECTOR pull is missing. ``attribution_params`` overrides the
    sector-vs-stock-specific bands (see ``attribution.PARAMS``).

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

    per_ticker: Dict[str, Dict[str, Any]] = {}
    rows: List[Dict[str, Any]] = []
    for tkr, recs in tickers.items():
        try:
            m = _ticker_metrics(
                recs, str(tkr), hsi,
                fundamentals=fundamentals_all.get(str(tkr)),
                sector_fallback=universe_sectors.get(str(tkr)),
            )
        except Exception:  # noqa: BLE001 — pure module must never raise
            m = {"symbol": str(tkr), "n_bars": 0}
        per_ticker[str(tkr)] = m
        rows.append(m)

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
    }

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
        "meta": meta,
    }
