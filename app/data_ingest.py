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
_NAME_ALIASES = ["company_name", "company name", "fg_company_name", "name",
                 "company", "security", "security_name", "description"]
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
        "event_date": _find_col(cols, ["event_date", "event date", "next_earnings",
                                       "next earnings", "earnings_date", "earnings date",
                                       "next_event", "next event", "fe_rep_dt_next",
                                       "report_date", "report date"]),
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
    # event_date stays as-is (parsed/validated downstream); blank if absent.

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


def _parse_dates(series: pd.Series) -> pd.Series:
    """Parse a date column that may be normal date strings OR numeric serials.

    The spill date formula uses FactSet ``JULIAN(...)``, which (like Excel) counts
    days from 1899-12-30, so refreshed values can arrive as integers/serials. If
    the column is predominantly numeric in the plausible serial range
    (~1990..2050 => ~33000..55000), convert via the 1899-12-30 origin; otherwise
    fall back to normal datetime parsing.
    """
    num = pd.to_numeric(series, errors="coerce")
    n_total = series.notna().sum()
    n_num = num.notna().sum()
    if n_total and n_num >= 0.8 * n_total:
        med = float(num.dropna().median()) if n_num else 0.0
        if 20000 <= med <= 80000:  # Excel/FactSet-Julian serial day range
            return pd.to_datetime(num, unit="D", origin="1899-12-30", errors="coerce")
    return pd.to_datetime(series, errors="coerce")


def _read_multisheet_spill(content: bytes, filename: str):
    """If the upload is a multi-sheet spill workbook (one per-ticker sheet, each
    with A2=ticker and date/close/volume columns), read & concatenate ALL ticker
    sheets into a tidy frame. Returns (tidy_df, report) or None if not applicable.
    """
    name = (filename or "").lower()
    if not (name.endswith(".xlsx") or name.endswith(".xls")):
        return None
    try:
        xls = pd.read_excel(io.BytesIO(content), sheet_name=None, header=0)
    except Exception:
        return None
    if not xls or len(xls) < 2:
        return None

    frames = []
    factset_errs = 0
    date_reconstructed = False
    skip = {"instructions", "readme", "info", "alltickers"}
    sheet_count = 0
    for sheet_name, sdf in xls.items():
        if str(sheet_name).strip().lower() in skip:
            continue
        if sdf is None or sdf.empty:
            continue
        sdf = _norm_cols(sdf)
        scols = list(sdf.columns)
        s_tkr = _find_col(scols, _TICKER_ALIASES)
        s_date = _find_col(scols, _DATE_ALIASES)
        s_price = _find_col(scols, _PRICE_ALIASES)
        s_vol = _find_col(scols, _VOLUME_ALIASES)
        s_name = _find_col([c for c in scols if c != s_tkr], _NAME_ALIASES)
        if not s_price:
            continue  # not a price sheet
        sheet_count += 1
        # Ticker: prefer the in-sheet ticker cell (A2), else the sheet name.
        if s_tkr and sdf[s_tkr].astype(str).str.strip().replace(
                {"": None, "nan": None, "None": None}).dropna().shape[0] > 0:
            tkr_val = (
                sdf[s_tkr].astype(str).str.strip()
                .replace({"": None, "nan": None, "None": None}).dropna().iloc[0]
            )
        else:
            tkr_val = str(sheet_name).strip()

        out = pd.DataFrame(index=sdf.index)
        out["close"], e1 = _scrub_factset(sdf[s_price])
        factset_errs += e1
        if s_vol and s_vol in sdf.columns:
            out["volume"], e2 = _scrub_factset(sdf[s_vol])
            factset_errs += e2
        else:
            out["volume"] = np.nan
        if s_date and s_date in sdf.columns:
            out["date"] = _parse_dates(sdf[s_date]).values
        else:
            out["date"] = pd.NaT
        # drop rows with no price (blank spill tail / ticker-only A2 row)
        out = out[out["close"].notna()].reset_index(drop=True)
        if out.empty:
            continue
        # If dates are all missing/blank, reconstruct from row order.
        if pd.Series(out["date"]).notna().sum() == 0:
            out["date"] = _reconstruct_dates(len(out)).values
            date_reconstructed = True
        out["ticker"] = tkr_val
        # Company name from this sheet's company_name column (first non-blank).
        nm_val = None
        if s_name and s_name in sdf.columns:
            for v in sdf[s_name].tolist():
                nm_val = _clean_name_value(v)
                if nm_val:
                    break
        out["name"] = nm_val
        frames.append(out[["ticker", "date", "close", "volume", "name"]])

    # Require it to actually look like a multi-ticker spill workbook.
    if sheet_count < 1 or not frames:
        return None
    tidy = pd.concat(frames, ignore_index=True)
    tidy = tidy.dropna(subset=["date"])
    tidy = tidy[tidy["ticker"].astype(str).str.lower() != "nan"]
    tidy = tidy.sort_values(["ticker", "date"]).reset_index(drop=True)
    report = build_quality_report(tidy, factset_errs)
    report["date_reconstructed"] = bool(date_reconstructed)
    report["multisheet_spill"] = True
    report["sheets_read"] = int(sheet_count)
    return tidy, report


def _clean_name_value(v: Any) -> str | None:
    """Return a clean company-name string, or None if blank / a FactSet error."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return None
    # Reject FactSet error placeholders that may land in a name cell.
    if s.upper() in {e.upper() for e in FACTSET_ERRORS}:
        return None
    # Strip stray control / box artifacts FactSet sometimes appends.
    s = "".join(ch for ch in s if ch == " " or (ch.isprintable() and ch not in "\u25a0\u25aa")).strip()
    return s or None


def _attach_name_from_dump(tidy: pd.DataFrame, src: pd.DataFrame,
                           ticker_col: str, name_col: str | None) -> pd.DataFrame:
    """Attach a per-ticker ``name`` column to the tidy price frame from the data
    dump's company-name column (first non-blank value per ticker). Never raises;
    returns ``tidy`` unchanged when no usable name column is present.
    """
    if not name_col or name_col not in src.columns or ticker_col not in src.columns:
        return tidy
    try:
        tk = src[ticker_col].astype(str).str.strip()
        nm = src[name_col].map(_clean_name_value)
        mapping: Dict[str, str] = {}
        for t, n in zip(tk, nm):
            if not t or t.lower() in ("nan", "none", ""):
                continue
            if n and t not in mapping:
                mapping[t] = n
        if mapping:
            tidy = tidy.copy()
            tidy["name"] = tidy["ticker"].astype(str).str.strip().map(mapping)
    except Exception:
        return tidy
    return tidy


def _reconstruct_dates(n: int) -> pd.Series:
    """Descending business days from today for n rows (row 0 = latest)."""
    if n <= 0:
        return pd.Series([], dtype="datetime64[ns]")
    cal = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    # row 0 = most recent -> cal[-1]; row k -> cal[-1-k]
    return pd.Series([cal[-1 - k] for k in range(n)])


def parse_prices(content: bytes, filename: str = "") -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Parse price data. Supports tidy (ticker,date,close,volume), wide, OR a
    multi-sheet spill workbook (one per-ticker sheet each, A2=ticker, B/C/D
    spilled down).

    Returns (tidy_df, quality_report). tidy columns: ticker, date, close, volume
    """
    # Multi-sheet spill workbook: each ticker on its OWN sheet. Detect and
    # concatenate ALL ticker sheets into one tidy frame before normal parsing.
    ms = _read_multisheet_spill(content, filename)
    if ms is not None:
        return ms

    raw = _read_any(content, filename)
    df = _norm_cols(raw)
    cols = list(df.columns)

    ticker_col = _find_col(cols, _TICKER_ALIASES)
    date_col = _find_col(cols, _DATE_ALIASES)
    price_col = _find_col(cols, _PRICE_ALIASES)
    vol_col = _find_col(cols, _VOLUME_ALIASES)
    # Company-name column from the data dump (optional). Exclude the ticker
    # column itself so we never mistake the identifier for the name.
    name_col = _find_col([c for c in cols if c != ticker_col], _NAME_ALIASES)

    # Spill per-ticker sheet uploaded directly: the ticker literal sits only in
    # the first data row (A2) while close/volume spill down many rows below it.
    # If a ticker column exists but is mostly blank/NaN while the price column is
    # much longer, FORWARD-FILL the ticker down so every spilled row is labeled.
    # (Don't touch the normal tidy path where the ticker repeats every row.)
    if ticker_col and price_col and ticker_col in df.columns:
        tser = df[ticker_col].astype(str).str.strip()
        blank = df[ticker_col].isna() | tser.isin(["", "nan", "NaN", "None"])
        n_nonblank = int((~blank).sum())
        n_price = int(df[price_col].notna().sum())
        if 0 < n_nonblank <= max(1, len(df) // 2) and n_price > n_nonblank:
            df[ticker_col] = df[ticker_col].where(~blank, other=pd.NA).ffill()

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
        tidy["date"] = _parse_dates(df[date_col])
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
        df["date"] = _parse_dates(df["date"])
        value_cols = [c for c in df.columns if c != "date"]
        long = df.melt(id_vars=["date"], value_vars=value_cols, var_name="ticker", value_name="close")
        long["close"], e1 = _scrub_factset(long["close"])
        factset_errs += e1
        long["volume"] = np.nan
        tidy = long[["ticker", "date", "close", "volume"]]

    tidy = tidy.dropna(subset=["date"])
    tidy = tidy[tidy["ticker"].astype(str).str.lower() != "nan"]
    tidy = tidy.sort_values(["ticker", "date"]).reset_index(drop=True)
    # Attach company name from the dump (if a name column was present) so the
    # screen can label names even when the universe file lacked a name column.
    if ticker_col:
        tidy = _attach_name_from_dump(tidy, df, ticker_col, name_col)

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
