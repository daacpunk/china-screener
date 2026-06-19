"""Tolerant parsing of uploaded universe + price files and data-quality report.

Pure-ish: takes raw bytes/text in, returns DataFrames + report dicts. No web deps.
Supports tidy time-series export OR an offset-grid layout for prices.
"""
from __future__ import annotations

import io
import re as _re
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

# FactSet error strings to scrub
FACTSET_ERRORS = ["#N/A", "@NA", "#ERR", "N/A", "NA", "#VALUE!", "#NAME?", "NaN", "@FORMULA"]

_PRICE_ALIASES = ["close", "price", "p_price", "adj close", "adj_close", "closing price", "px_last"]
_VOLUME_ALIASES = ["volume", "vol", "p_volume", "turnover", "trd_volume"]
_DATE_ALIASES = ["date", "p_date", "asof", "as_of", "trade_date"]
_TICKER_ALIASES = [
    "ticker", "symbol", "fsym_id", "id", "sec_id", "request_id",
    "ric", "bbg", "bloomberg", "sedol", "isin", "code", "stock code",
    "factset ticker", "fs ticker", "identifier",
]


# Tokens we expect to find in a real header row (helps locate it when the file
# has title/metadata rows above the actual column headers — common in FactSet
# and MSCI Excel exports).
_HEADER_HINTS = (
    _TICKER_ALIASES
    + ["name", "company", "security", "sector", "industry", "weight", "adv",
       "close", "price", "date", "volume"]
)


def _looks_like_header(values: List[Any]) -> int:
    """Score a candidate header row by how many cells match expected tokens."""
    score = 0
    for v in values:
        s = str(v).strip().lower()
        if not s or s == "nan":
            continue
        for hint in _HEADER_HINTS:
            if hint == s or hint in s:
                score += 1
                break
    return score


def _read_any(content: bytes, filename: str) -> pd.DataFrame:
    name = (filename or "").lower()
    is_excel = name.endswith(".xlsx") or name.endswith(".xls")

    def _read_with_header(hdr):
        if is_excel:
            return pd.read_excel(io.BytesIO(content), header=hdr)
        # python engine + skip-bad-lines tolerates ragged rows once the header
        # row is known (extra/fewer fields in stray rows won't abort the read).
        for enc in ("utf-8", "latin-1"):
            try:
                return pd.read_csv(
                    io.BytesIO(content), header=hdr,
                    engine="python", on_bad_lines="skip", encoding=enc,
                )
            except Exception:
                continue
        return pd.read_csv(io.BytesIO(content), header=hdr)

    # Probe the first ~15 physical rows to locate the real header row. We split
    # text manually (NOT via pandas) so ragged title rows can't confuse the
    # delimiter sniffer or get silently skipped.
    best_row = 0
    if is_excel:
        try:
            probe = pd.read_excel(io.BytesIO(content), header=None, nrows=15)
            best_score = -1
            for i in range(len(probe)):
                sc = _looks_like_header(list(probe.iloc[i].values))
                if sc > best_score:
                    best_row, best_score = i, sc
            if best_score < 2:
                best_row = 0
        except Exception:
            best_row = 0
    else:
        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            text = content.decode("latin-1", errors="replace")
        lines = text.splitlines()[:15]
        # pick delimiter: comma or tab, whichever appears more in the lines
        delim = "\t" if sum(l.count("\t") for l in lines) > sum(l.count(",") for l in lines) else ","
        best_score = -1
        for i, line in enumerate(lines):
            cells = line.split(delim)
            sc = _looks_like_header(cells)
            if sc > best_score:
                best_row, best_score = i, sc
        if best_score < 2:
            best_row = 0
    return _read_with_header(best_row)


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _find_col(cols: List[str], aliases: List[str]) -> str | None:
    for a in aliases:
        if a in cols:
            return a
    # fuzzy contains
    for c in cols:
        for a in aliases:
            if a in c:
                return c
    return None


def parse_universe(content: bytes, filename: str = "",
                   overrides: Dict[str, str] | None = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Parse a universe file into normalized columns.

    Returns (df, mapping_report). df columns:
    ticker, name, sector, sub_industry, index_weight, adv_usd_20d

    `overrides` lets the caller force a target->source-column mapping (manual
    column mapping from the UI). Source names are matched case-insensitively.
    """
    raw = _read_any(content, filename)
    df = _norm_cols(raw)
    cols = list(df.columns)
    mapping = {
        "ticker": _find_col(cols, _TICKER_ALIASES),
        "name": _find_col(cols, ["name", "company", "security", "description"]),
        "sector": _find_col(cols, ["sector", "gics_sector", "gics sector"]),
        "sub_industry": _find_col(cols, ["sub_industry", "sub-industry", "subindustry", "gics_sub_industry", "sub industry"]),
        "index_weight": _find_col(cols, ["index_weight", "index weight", "weight", "wt"]),
        "adv_usd_20d": _find_col(cols, ["20d_adv_usd", "adv_usd", "adv", "20d adv usd", "adv_usd_20d"]),
    }
    # Apply manual overrides (UI column mapping) — normalized to lowercase.
    if overrides:
        for target, src in overrides.items():
            s = (src or "").strip().lower()
            if s and s in cols:
                mapping[target] = s
    out = pd.DataFrame()
    for target, src in mapping.items():
        out[target] = df[src] if src and src in df.columns else np.nan
    out["ticker"] = out["ticker"].astype(str).str.strip()
    out = out[out["ticker"].notna() & (out["ticker"] != "") & (out["ticker"].str.lower() != "nan")]
    out["index_weight"] = pd.to_numeric(out["index_weight"], errors="coerce")
    out["adv_usd_20d"] = pd.to_numeric(out["adv_usd_20d"], errors="coerce")

    # MSCI index-export enrichment: these files list GICS sector/sub-industry as
    # interleaved GROUP ROWS (blank symbol, name prefixed with a GICS code:
    # 2-digit = sector, 6/8-digit = sub-industry) followed by their constituents.
    # Derive sector/sub-industry per name and drop the group/index summary rows.
    msci = _enrich_msci_gics(df, mapping)
    if msci is not None:
        out = msci

    report = {"rows": int(len(out)), "mapping": mapping, "columns_seen": cols}
    return out.reset_index(drop=True), report


_GICS_ROW = _re.compile(r"^\s*(\d{2})(?:(\d{2})(\d{2,4}))?\s+(.*\S)\s*$")
# Identifiers that are index/aggregate rows, not tradable constituents.
_NON_CONSTITUENT_TICKERS = {"cn-msx", "", "nan", "-"}


def _enrich_msci_gics(df: pd.DataFrame, mapping: Dict[str, Any]):
    """If df looks like an MSCI index export, return an enriched constituent
    frame with sector/sub_industry derived from GICS group rows. Else None.

    Detection: a 'name' and 'symbol/ticker' column exist, no explicit sector
    column was mapped, and the name column contains GICS-coded group rows that
    have a blank symbol.
    """
    name_col = mapping.get("name")
    tkr_col = mapping.get("ticker")
    if not name_col or not tkr_col or mapping.get("sector"):
        return None
    if name_col not in df.columns or tkr_col not in df.columns:
        return None

    names = df[name_col].astype(str)
    syms = df[tkr_col].astype(str).str.strip()
    wt_col = mapping.get("index_weight")
    weights = df[wt_col] if wt_col and wt_col in df.columns else None

    # Count GICS-coded group rows that have a blank/dash symbol.
    group_like = 0
    for nm, sy in zip(names, syms):
        nm_s = str(nm).strip()
        sy_s = str(sy).strip().lower()
        if sy_s in _NON_CONSTITUENT_TICKERS and _GICS_ROW.match(nm_s):
            group_like += 1
    if group_like < 3:
        return None  # not an MSCI-style hierarchical export

    cur_sector = None
    cur_sub = None
    rows = []
    for i in range(len(df)):
        nm = str(names.iloc[i]).strip()
        sy = str(syms.iloc[i]).strip()
        sy_low = sy.lower()
        m = _GICS_ROW.match(nm)
        is_group = (sy_low in _NON_CONSTITUENT_TICKERS) and bool(m)
        if is_group:
            code2, code_mid, code_tail, label = m.group(1), m.group(2), m.group(3), m.group(4)
            if code_mid is None:
                # 2-digit -> GICS sector header; resets sub-industry
                cur_sector = label.strip()
                cur_sub = None
            else:
                # 6/8-digit -> sub-industry header under the current sector
                cur_sub = label.strip()
            continue
        # Constituent row: must have a real symbol
        if sy_low in _NON_CONSTITUENT_TICKERS:
            continue
        rows.append({
            "ticker": sy,
            "name": nm,
            "sector": cur_sector,
            "sub_industry": cur_sub,
            "index_weight": pd.to_numeric(weights.iloc[i], errors="coerce") if weights is not None else np.nan,
            "adv_usd_20d": np.nan,
        })
    if not rows:
        return None
    return pd.DataFrame(rows)


def _scrub_factset(series: pd.Series) -> Tuple[pd.Series, int]:
    s = series.astype(str).str.strip()
    err_mask = s.str.upper().isin([e.upper() for e in FACTSET_ERRORS]) | s.str.startswith("#")
    n_err = int(err_mask.sum())
    cleaned = pd.to_numeric(series.where(~err_mask), errors="coerce")
    return cleaned, n_err


def parse_prices(content: bytes, filename: str = "") -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Parse price data. Supports tidy (ticker,date,close,volume) or wide.

    Returns (tidy_df, quality_report). tidy columns: ticker, date, close, volume
    """
    raw = _read_any(content, filename)
    df = _norm_cols(raw)
    cols = list(df.columns)

    ticker_col = _find_col(cols, _TICKER_ALIASES)
    date_col = _find_col(cols, _DATE_ALIASES)
    price_col = _find_col(cols, _PRICE_ALIASES)
    vol_col = _find_col(cols, _VOLUME_ALIASES)

    factset_errs = 0
    date_reconstructed = False
    if ticker_col and price_col and not date_col:
        # No date column (efficient pull dropped it). Reconstruct dates from ROW
        # ORDER per ticker: the generated grid is most-recent-first (row 1 =
        # latest trading day), so assign descending business days from today.
        # Indicators only need correct chronological ORDER, not exact calendar
        # dates; the event-flag (which needs real dates) degrades gracefully.
        tidy = pd.DataFrame()
        tidy["ticker"] = df[ticker_col].astype(str).str.strip()
        tidy["close"], e1 = _scrub_factset(df[price_col])
        factset_errs += e1
        if vol_col and vol_col in df.columns:
            tidy["volume"], e2 = _scrub_factset(df[vol_col])
            factset_errs += e2
        else:
            tidy["volume"] = np.nan
        tidy["__pos"] = tidy.groupby("ticker").cumcount()  # 0 = first row = latest
        max_off = int(tidy["__pos"].max()) if len(tidy) else 0
        cal = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=max_off + 1)
        # offset 0 -> last (latest) calendar day; offset k -> k business days back
        tidy["date"] = tidy["__pos"].map(lambda k: cal[-1 - int(k)])
        tidy = tidy.drop(columns="__pos")
        date_reconstructed = True
    elif ticker_col and date_col and price_col:
        # tidy
        tidy = pd.DataFrame()
        tidy["ticker"] = df[ticker_col].astype(str).str.strip()
        tidy["date"] = pd.to_datetime(df[date_col], errors="coerce")
        tidy["close"], e1 = _scrub_factset(df[price_col])
        factset_errs += e1
        if vol_col and vol_col in df.columns:
            tidy["volume"], e2 = _scrub_factset(df[vol_col])
            factset_errs += e2
        else:
            tidy["volume"] = np.nan
        # If a date column exists but parsed entirely to NaT (e.g. P_DATE came
        # back blank), fall back to row-order reconstruction too.
        if tidy["date"].notna().sum() == 0:
            tidy["__pos"] = tidy.groupby("ticker").cumcount()
            max_off = int(tidy["__pos"].max()) if len(tidy) else 0
            cal = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=max_off + 1)
            tidy["date"] = tidy["__pos"].map(lambda k: cal[-1 - int(k)])
            tidy = tidy.drop(columns="__pos")
            date_reconstructed = True
    else:
        # attempt wide -> tidy: first col dates, remaining columns tickers (close)
        if not date_col:
            date_col = cols[0]
        df = df.rename(columns={date_col: "date"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        value_cols = [c for c in df.columns if c != "date"]
        long = df.melt(id_vars=["date"], value_vars=value_cols, var_name="ticker", value_name="close")
        long["close"], e1 = _scrub_factset(long["close"])
        factset_errs += e1
        long["volume"] = np.nan
        tidy = long[["ticker", "date", "close", "volume"]]

    tidy = tidy.dropna(subset=["date"])
    tidy = tidy[tidy["ticker"].astype(str).str.lower() != "nan"]
    tidy = tidy.sort_values(["ticker", "date"]).reset_index(drop=True)

    report = build_quality_report(tidy, factset_errs)
    report["date_reconstructed"] = bool(date_reconstructed)
    return tidy, report


def build_quality_report(tidy: pd.DataFrame, factset_errs: int = 0, min_bars: int = 60) -> Dict[str, Any]:
    per_ticker = []
    short = []
    nan_tickers = []
    for tkr, g in tidy.groupby("ticker"):
        n = int(g["close"].notna().sum())
        nans = int(g["close"].isna().sum())
        last_date = g["date"].max()
        per_ticker.append({
            "ticker": tkr, "bars": n, "nan_close": nans,
            "last_date": str(last_date.date()) if pd.notna(last_date) else None,
        })
        if n < min_bars:
            short.append(tkr)
        if nans > 0:
            nan_tickers.append(tkr)
    return {
        "total_rows": int(len(tidy)),
        "n_tickers": int(tidy["ticker"].nunique()),
        "factset_error_cells": int(factset_errs),
        "short_series": short,
        "tickers_with_nans": nan_tickers,
        "per_ticker": per_ticker,
    }


def tidy_to_csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False)


def csv_to_df(csv_text: str) -> pd.DataFrame:
    if not csv_text:
        return pd.DataFrame()
    return pd.read_csv(io.StringIO(csv_text))
