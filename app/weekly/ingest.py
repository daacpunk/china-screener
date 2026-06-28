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
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .. import data_ingest as di
from .. import screen_engine as se
from . import HSI_FACTSET_ID
from . import template_gen as wtpl

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


# Characters that show up as rendering artifacts in FactSet text pulls (the
# black-square ■ = U+25A0 / replacement char, control chars, BOM, etc.). We keep
# only printable text + common typographic punctuation, then collapse whitespace.
_ARTIFACT_RE = re.compile("[\u25a0\ufffd\ufeff\u0000-\u001f\u007f-\u009f]")
_WS_RE = re.compile(r"\s+")


def clean_text_artifacts(s: Any) -> Optional[str]:
    """Strip ■/non-printable/control artifacts from a FactSet text value and
    collapse runs of whitespace. Returns a clean str, or None when nothing
    printable remains. Never raises."""
    if s is None:
        return None
    try:
        txt = str(s)
    except Exception:  # noqa: BLE001
        return None
    # Normalize unicode, drop explicit artifact chars, then drop any remaining
    # non-printable codepoints (keep normal printable incl. unicode letters).
    txt = unicodedata.normalize("NFKC", txt)
    txt = _ARTIFACT_RE.sub(" ", txt)
    txt = "".join(ch for ch in txt if ch.isprintable() or ch.isspace())
    txt = _WS_RE.sub(" ", txt).strip()
    return txt or None


_FUND_LABEL_HEADERS = {"fundamental", "fundamentals", "field", "metric"}
_FUND_VALUE_HEADERS = {"value (point-in-time)", "value", "point-in-time", "pit"}
# FactSet NA/error markers that must coerce to None (case-insensitive).
_FUND_NA = {s.lower() for s in di.FACTSET_ERRORS} | {"", "none", "nat"}


def _clean_fund_value(raw: Any, key: str) -> Any:
    """Coerce one populated fundamental cell into a stored value: None for blanks /
    FactSet NA markers; float for numeric fields; trimmed str for GICS text."""
    if raw is None:
        return None
    try:
        if isinstance(raw, float) and pd.isna(raw):
            return None
    except Exception:  # noqa: BLE001
        pass
    s = str(raw).strip()
    if s == "" or s.lower() in _FUND_NA:
        return None
    if key in wtpl.FUNDAMENTAL_TEXT_KEYS:
        # Strip ■/non-printable artifacts and collapse whitespace so names and
        # descriptions render cleanly everywhere (md/html/docx/pdf).
        cleaned = clean_text_artifacts(s)
        if cleaned is None:
            return None
        # A value that was nothing but artifacts/NA after cleaning -> None.
        if cleaned.lower() in _FUND_NA:
            return None
        return cleaned
    # numeric field
    try:
        v = float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _fundamentals_from_sheet(sdf: pd.DataFrame) -> Dict[str, Any]:
    """Parse the per-ticker point-in-time fundamentals block (label column +
    value column) into {key: value|None}. Maps the populated label cells back to
    canonical keys via the template's label map. Tolerates blanks / NA / a
    missing block (returns {} when no recognizable labels are present). Never
    raises."""
    out: Dict[str, Any] = {}
    if sdf is None or sdf.empty:
        return out
    try:
        df = di._norm_cols(sdf)
        cols = list(df.columns)
        # Locate the label + value columns by header name first.
        label_col = next((c for c in cols if str(c).strip().lower() in _FUND_LABEL_HEADERS), None)
        value_col = next((c for c in cols if str(c).strip().lower() in _FUND_VALUE_HEADERS), None)
        # Fallback: scan every column for one whose cells match known labels.
        if label_col is None:
            norm_labels = {lbl.strip().lower(): key
                           for lbl, key in wtpl.FUNDAMENTAL_LABEL_TO_KEY.items()}
            for c in cols:
                series = df[c].astype(str).str.strip().str.lower()
                if series.isin(norm_labels.keys()).sum() >= 2:
                    label_col = c
                    # value column = the next column to the right if any.
                    ci = cols.index(c)
                    value_col = cols[ci + 1] if ci + 1 < len(cols) else None
                    break
        if label_col is None or value_col is None:
            return out
        norm_map = {lbl.strip().lower(): key
                    for lbl, key in wtpl.FUNDAMENTAL_LABEL_TO_KEY.items()}
        for _, row in df.iterrows():
            lbl = str(row.get(label_col) or "").strip().lower()
            key = norm_map.get(lbl)
            if not key:
                continue
            out[key] = _clean_fund_value(row.get(value_col), key)
    except Exception:  # noqa: BLE001 — fundamentals are best-effort
        return out
    return out


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
    fundamentals: Dict[str, Dict[str, Any]] = {}
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
        # Point-in-time fundamentals block (best-effort; absent -> {}).
        fnd = _fundamentals_from_sheet(sdf)
        if fnd:
            fundamentals[tkr] = fnd
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

    n_fund = sum(1 for v in fundamentals.values()
                 if any(x is not None for x in v.values()))
    meta = {
        "n_tickers": len(tickers),
        "hsi_loaded": bool(hsi_records),
        "n_partial": len(partial),
        "n_fundamentals": n_fund,
        "latest_per_ticker": (max(last_dates).date().isoformat() if last_dates else None),
        "hsi_last": (hsi_last.date().isoformat() if hsi_last is not None else None),
        "source": filename or "",
    }
    out: Dict[str, Any] = {
        "asof": asof,
        "n_stale": n_stale,
        "stale": bool(stale),
        "tickers": tickers,
        "fundamentals": fundamentals,
        "hsi": hsi_records,
        "partial": sorted(partial),
        "meta": meta,
    }
    if not tickers and not hsi_records:
        out["error"] = ("No ticker or HSI series were read. Make sure you ran the "
                        "ActivateSpills macro so the formulas filled in.")
    return out


# ---------------------------------------------------------------------------
# Multi-file merge (Phase D: split-template re-upload)
# ---------------------------------------------------------------------------
def _last_date(records: List[Dict[str, Any]]) -> Optional[pd.Timestamp]:
    """Latest non-null ``date`` across a list of {date,...} records."""
    ds = []
    for r in records or []:
        d = r.get("date")
        if d:
            ts = pd.Timestamp(d)
            if pd.notna(ts):
                ds.append(ts)
    return max(ds) if ds else None


def _n_valid(records: List[Dict[str, Any]], field: str = "close") -> int:
    """Count records with a non-null value in ``field`` (richness measure)."""
    n = 0
    for r in records or []:
        if r.get(field) is not None:
            n += 1
    return n


def _dedupe_by_date(
    records: List[Dict[str, Any]], fields: List[str]
) -> List[Dict[str, Any]]:
    """Union of records keyed by ISO date; prefer the first non-null value per
    field, then sort chronological. Records without a date are kept as-is at the
    end (order-preserving)."""
    by_date: Dict[str, Dict[str, Any]] = {}
    undated: List[Dict[str, Any]] = []
    for r in records or []:
        d = r.get("date")
        if not d:
            undated.append(dict(r))
            continue
        key = str(d)
        cur = by_date.get(key)
        if cur is None:
            by_date[key] = {"date": d, **{f: r.get(f) for f in fields}}
        else:
            for f in fields:
                if cur.get(f) is None and r.get(f) is not None:
                    cur[f] = r.get(f)
    merged = [by_date[k] for k in sorted(by_date.keys())]
    return merged + undated


def merge_weekly_parsed(parsed_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge several ``parse_weekly_workbook`` dicts (one per uploaded split
    file) into a single combined snapshot dict, BEFORE persistence.

    Reconciliation rules:
      * ``tickers``: union across files. On a duplicate ticker, keep the series
        with more valid closes (ties -> existing); never lose data.
      * ``hsi``: every split file carries the same HSI sheet -- take the union of
        dates, dedupe by date (prefer the first non-null close), sort chrono.
      * ``asof``: recompute as the latest COMMON date across all merged ticker
        series (+ HSI if present) -- the MIN of each series' last date.
      * ``partial``: union of per-file partial flags.
      * errors: aggregated into a combined ``error`` string. Only a hard error
        (no tickers AND no HSI anywhere) blocks the caller.
      * ``sources``: list of source filenames; ``meta`` aggregates counts.

    Pure / never raises. A 1-element list merges to an equivalent single dict.
    """
    items = [p for p in (parsed_list or []) if isinstance(p, dict)]
    tickers: Dict[str, List[Dict[str, Any]]] = {}
    fundamentals: Dict[str, Dict[str, Any]] = {}
    hsi_all: List[Dict[str, Any]] = []
    partial_set: set = set()
    sources: List[str] = []
    file_errors: List[str] = []
    n_files = 0

    for p in items:
        n_files += 1
        src = (p.get("meta") or {}).get("source") or ""
        sources.append(str(src) if src else f"file_{n_files}")
        err = p.get("error")
        if err:
            file_errors.append(str(err))
        # Merge tickers (keep the richer series on collision).
        for tkr, recs in (p.get("tickers") or {}).items():
            if not tkr:
                continue
            if tkr not in tickers:
                tickers[tkr] = list(recs or [])
            else:
                if _n_valid(recs) > _n_valid(tickers[tkr]):
                    tickers[tkr] = list(recs or [])
        # Merge fundamentals (prefer a record with more non-null fields).
        for tkr, fnd in (p.get("fundamentals") or {}).items():
            if not tkr or not isinstance(fnd, dict):
                continue
            cur = fundamentals.get(tkr)
            if cur is None:
                fundamentals[tkr] = dict(fnd)
            else:
                cur_n = sum(1 for v in cur.values() if v is not None)
                new_n = sum(1 for v in fnd.values() if v is not None)
                if new_n > cur_n:
                    fundamentals[tkr] = dict(fnd)
        # Accumulate HSI for cross-file dedupe.
        hsi_all.extend(p.get("hsi") or [])
        for t in (p.get("partial") or []):
            partial_set.add(t)

    hsi_records = _dedupe_by_date(hsi_all, ["close"])

    # as-of = latest COMMON date: MIN over each series' last date (+ HSI).
    last_dates: List[pd.Timestamp] = []
    for recs in tickers.values():
        ld = _last_date(recs)
        if ld is not None:
            last_dates.append(ld)
    hsi_last = _last_date(hsi_records)
    common = list(last_dates)
    if hsi_last is not None:
        common.append(hsi_last)
    asof: Optional[str] = None
    if common:
        asof = min(common).date().isoformat()

    n_stale = se.days_stale(asof) if asof else None
    stale = (n_stale is not None) and (n_stale > 3)

    combined_error: Optional[str] = None
    if not tickers and not hsi_records:
        combined_error = ("No ticker or HSI series were read from any file. Make "
                          "sure you ran the ActivateSpills macro so the formulas "
                          "filled in.")
    elif file_errors:
        # Soft warning -- surfaced but non-blocking.
        combined_error = "; ".join(dict.fromkeys(file_errors))

    meta = {
        "n_tickers": len(tickers),
        "hsi_loaded": bool(hsi_records),
        "n_partial": len(partial_set),
        "n_files": n_files,
        "sources": sources,
        "latest_per_ticker": (max(last_dates).date().isoformat() if last_dates else None),
        "hsi_last": (hsi_last.date().isoformat() if hsi_last is not None else None),
        "source": ", ".join(sources),
    }
    out: Dict[str, Any] = {
        "asof": asof,
        "n_stale": n_stale,
        "stale": bool(stale),
        "tickers": tickers,
        "fundamentals": fundamentals,
        "hsi": hsi_records,
        "partial": sorted(partial_set),
        "sources": sources,
        "meta": meta,
    }
    if combined_error:
        out["error"] = combined_error
    return out
