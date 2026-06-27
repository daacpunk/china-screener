"""Phase D weekly data ingestion.

Reads the populated multi-sheet spill workbook produced by template_gen:
  - One sheet per ticker (A2 = ticker literal; B/C/D = date/close/volume spilled).
  - A dedicated "HSI" sheet (A2 = "180458"; B/C = date/close).
  - Instructions / Manifest sheets (skipped).

Reuses the proven helpers in app/data_ingest (column detection, FactSet error
scrubbing, JULIAN-date decoding, row-order date reconstruction). Produces a
dated weekly snapshot dict suitable for snapshot_store + metrics:

    {
      "asof": "YYYY-MM-DD" | None,          # latest COMMON date across tickers+HSI
      "stale": bool, "n_stale": int|None,   # 3-trading-day staleness rule
      "tickers": {ticker: [{date,close,volume}, ...]},  # chronological
      "hsi": [{date, close}, ...],          # chronological
      "partial": [ticker, ...],             # < min_bars history
      "meta": {...}
    }

Pure-ish: takes raw bytes in, returns a JSON-serializable dict. No web/DB deps.
"""
from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .. import data_ingest as di
from .. import screen_engine as se
from . import HSI_FACTSET_ID

# Minimum contiguous bars before a ticker is treated as full-history (else it is
# flagged partial). 63 td ~= one quarter; enough for the 1M/3M momentum windows.
MIN_BARS = 63

_SKIP_SHEETS = {"instructions", "readme", "info", "manifest", "alltickers"}
_HSI_SHEET_NAMES = {"hsi", "180458", "benchmark", "index"}


def _series_from_sheet(sdf: pd.DataFrame) -> Optional[Tuple[str, pd.DataFrame]]:
    """Parse one ticker sheet into (ticker, frame[date,close,volume]) or None."""
    if sdf is None or sdf.empty:
        return None
    sdf = di._norm_cols(sdf)
    scols = list(sdf.columns)
    s_tkr = di._find_col(scols, di._TICKER_ALIASES)
    s_date = di._find_col(scols, di._DATE_ALIASES)
    s_price = di._find_col(scols, di._PRICE_ALIASES)
    s_vol = di._find_col(scols, di._VOLUME_ALIASES)
    if not s_price:
        return None

    # Ticker: prefer the in-sheet A2 literal, else fall back to caller's sheet name.
    tkr_val = None
    if s_tkr and s_tkr in sdf.columns:
        nz = (sdf[s_tkr].astype(str).str.strip()
              .replace({"": None, "nan": None, "None": None}).dropna())
        if nz.shape[0] > 0:
            tkr_val = nz.iloc[0]

    out = pd.DataFrame(index=sdf.index)
    out["close"], _ = di._scrub_factset(sdf[s_price])
    if s_vol and s_vol in sdf.columns:
        out["volume"], _ = di._scrub_factset(sdf[s_vol])
    else:
        out["volume"] = np.nan
    if s_date and s_date in sdf.columns:
        out["date"] = di._parse_dates(sdf[s_date]).values
    else:
        out["date"] = pd.NaT
    out = out[out["close"].notna()].reset_index(drop=True)
    if out.empty:
        return None
    # Reconstruct dates from row order if all missing (most-recent-first).
    if pd.Series(out["date"]).notna().sum() == 0:
        out["date"] = di._reconstruct_dates(len(out)).values
    out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if out.empty:
        return None
    return tkr_val, out[["date", "close", "volume"]]


def _frame_records(df: pd.DataFrame, cols: List[str]) -> List[Dict[str, Any]]:
    recs = []
    for _, row in df.iterrows():
        rec: Dict[str, Any] = {}
        for c in cols:
            v = row.get(c)
            if c == "date":
                rec["date"] = pd.Timestamp(v).date().isoformat() if pd.notna(v) else None
            else:
                rec[c] = float(v) if pd.notna(v) else None
        recs.append(rec)
    return recs


def parse_weekly_workbook(content: bytes, filename: str = "") -> Dict[str, Any]:
    """Parse the populated weekly workbook into a snapshot dict. Never raises on
    a structurally-odd file — returns a dict with an ``error`` key instead."""
    name = (filename or "").lower()
    if not (name.endswith(".xlsx") or name.endswith(".xls")):
        return {"error": "Please upload the populated .xlsx weekly template.",
                "tickers": {}, "hsi": [], "asof": None, "partial": []}
    try:
        xls = pd.read_excel(io.BytesIO(content), sheet_name=None, header=0)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not read the workbook: {e}",
                "tickers": {}, "hsi": [], "asof": None, "partial": []}
    if not xls:
        return {"error": "The workbook had no readable sheets.",
                "tickers": {}, "hsi": [], "asof": None, "partial": []}

    tickers: Dict[str, List[Dict[str, Any]]] = {}
    hsi_records: List[Dict[str, Any]] = []
    partial: List[str] = []
    last_dates: List[pd.Timestamp] = []
    hsi_last: Optional[pd.Timestamp] = None

    for sheet_name, sdf in xls.items():
        key = str(sheet_name).strip().lower()
        if key in _SKIP_SHEETS:
            continue
        parsed = _series_from_sheet(sdf)
        if parsed is None:
            continue
        in_sheet_tkr, frame = parsed
        is_hsi = key in _HSI_SHEET_NAMES or str(in_sheet_tkr).strip() == HSI_FACTSET_ID
        if is_hsi:
            hsi_records = _frame_records(frame, ["date", "close"])
            d = frame["date"].max()
            hsi_last = pd.Timestamp(d) if pd.notna(d) else None
            continue
        tkr = (str(in_sheet_tkr).strip() if in_sheet_tkr else str(sheet_name).strip())
        if not tkr or tkr.lower() == "nan":
            continue
        tickers[tkr] = _frame_records(frame, ["date", "close", "volume"])
        n = int(frame["close"].notna().sum())
        if n < MIN_BARS:
            partial.append(tkr)
        d = frame["date"].max()
        if pd.notna(d):
            last_dates.append(pd.Timestamp(d))

    # as-of = latest COMMON date across tickers (+HSI if present). Use the MIN of
    # each series' last date so the headline date is one every series reaches.
    asof: Optional[str] = None
    common_candidates = list(last_dates)
    if hsi_last is not None:
        common_candidates.append(hsi_last)
    if common_candidates:
        asof_ts = min(common_candidates)
        asof = asof_ts.date().isoformat()

    n_stale = se.days_stale(asof) if asof else None
    stale = (n_stale is not None) and (n_stale > 3)

    meta = {
        "n_tickers": len(tickers),
        "hsi_loaded": bool(hsi_records),
        "n_partial": len(partial),
        "latest_per_ticker": (max(last_dates).date().isoformat() if last_dates else None),
        "hsi_last": (hsi_last.date().isoformat() if hsi_last is not None else None),
        "source": filename or "",
    }
    out: Dict[str, Any] = {
        "asof": asof,
        "n_stale": n_stale,
        "stale": bool(stale),
        "tickers": tickers,
        "hsi": hsi_records,
        "partial": sorted(partial),
        "meta": meta,
    }
    if not tickers and not hsi_records:
        out["error"] = ("No ticker or HSI series were read. Make sure you ran the "
                        "ActivateSpills macro so the formulas filled in.")
    return out
