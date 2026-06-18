"""Tolerant parsing of uploaded universe + price files and data-quality report.

Pure-ish: takes raw bytes/text in, returns DataFrames + report dicts. No web deps.
Supports tidy time-series export OR an offset-grid layout for prices.
"""
from __future__ import annotations

import io
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
    report = {"rows": int(len(out)), "mapping": mapping, "columns_seen": cols}
    return out.reset_index(drop=True), report


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
    if ticker_col and date_col and price_col:
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
