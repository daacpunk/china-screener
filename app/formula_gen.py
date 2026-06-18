"""FactSet FQL formula generation.

Pure (no web/DB). Replicates the reference ``generate_formula`` exactly and
adds two layout builders plus a downloadable .xlsx builder.

Method A (preferred): per-ticker daily time-series block (dates column + close
+ volume) reproducing FactSet "Insert Formula -> Closing Price, Daily, -2Y".

Method B (fallback): generic offset grid using the active dictionary's
fql_template, e.g. =FDS($A$2,"P_PRICE(-"&(ROW()-3)&"D)").
"""
from __future__ import annotations

import io
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# Reference function — replicated EXACTLY (generalised via kwargs).
# ---------------------------------------------------------------------------
def generate_formula(ticker: str, metric_key: str, dictionary: dict, **kwargs) -> str:
    formulas = dictionary["formulas"]
    if metric_key not in formulas:
        return f"# ERROR: Unknown metric '{metric_key}'"
    template = formulas[metric_key]["fql_template"]
    for key, value in kwargs.items():
        placeholder = "{" + key + "}"
        if placeholder in template:
            template = template.replace(placeholder, str(value))
    return f'=FDS("{ticker}", "{template}")'


# ---------------------------------------------------------------------------
# Method A — time-series block per ticker.
# ---------------------------------------------------------------------------
def method_a_timeseries_formulas(
    ticker: str,
    dictionary: dict,
    start: str = "-2Y",
    end: str = "0D",
    freq: str = "D",
    price_metric: str = "price",
    volume_metric: str = "volume",
) -> Dict[str, str]:
    """Return the header FDS formulas for a daily date+close+volume block.

    FactSet returns the date axis automatically when a time-series formula is
    entered with a date range, so a single formula per series spills vertically.
    """
    formulas = dictionary.get("formulas", {})
    out: Dict[str, str] = {}
    if price_metric in formulas:
        out["close"] = generate_formula(
            ticker, price_metric, dictionary, start=start, end=end, freq=freq
        )
    else:
        out["close"] = f'=FDS("{ticker}", "P_PRICE({start}:{end}:{freq})")'
    if volume_metric in formulas:
        out["volume"] = generate_formula(
            ticker, volume_metric, dictionary, start=start, end=end, freq=freq
        )
    else:
        out["volume"] = f'=FDS("{ticker}", "P_VOLUME({start}:{end}:{freq})")'
    # date axis helper
    out["date"] = f'=FDS("{ticker}", "P_DATE({start}:{end}:{freq})")'
    return out


# ---------------------------------------------------------------------------
# Method B — offset grid fallback.
# ---------------------------------------------------------------------------
def method_b_offset_grid(
    dictionary: dict,
    lookback: int = 250,
    price_metric: str = "price",
    ticker_cell: str = "$A$2",
    header_rows: int = 3,
) -> List[Dict[str, Any]]:
    """Return a list of rows describing the offset-grid layout.

    Each row: {row, offset, relative_formula, explicit_date_formula}.
    relative pattern: =FDS($A$2,"P_PRICE(-"&(ROW()-3)&"D)")
    explicit pattern: =FDS($A$2,"P_PRICE("&B2&")")  (date in column B)
    """
    formulas = dictionary.get("formulas", {})
    base_fql = "P_PRICE"
    if price_metric in formulas:
        tmpl = formulas[price_metric].get("fql_template", "P_PRICE({start}:{end}:{freq})")
        # strip to the function root for offset usage
        base_fql = tmpl.split("(")[0] if "(" in tmpl else tmpl
    rows: List[Dict[str, Any]] = []
    for i in range(lookback):
        sheet_row = header_rows + 1 + i
        rel = f'=FDS({ticker_cell},"{base_fql}(-"&(ROW()-{header_rows})&"D)")'
        exp = f'=FDS({ticker_cell},"{base_fql}("&B{sheet_row}&")")'
        rows.append(
            {
                "row": sheet_row,
                "offset": i,
                "relative_formula": rel,
                "explicit_date_formula": exp,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Downloadable .xlsx builder.
# ---------------------------------------------------------------------------
HEADER_FILL = PatternFill("solid", fgColor="1f2937")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def _style_header(ws, ncols: int, row: int = 1):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT


def build_formula_workbook(
    tickers: List[str],
    dictionary: dict,
    method: str = "A",
    lookback: int = 250,
    start: str = "-2Y",
    end: str = "0D",
    freq: str = "D",
    layout: str = "per_ticker",  # 'per_ticker' or 'stacked'
) -> bytes:
    """Build the formula workbook as xlsx bytes.

    Method A:
      - per_ticker: one sheet per ticker with date/close/volume header formulas.
      - stacked: a single Instructions sheet + one sheet listing all tickers.
    Method B:
      - one sheet per ticker with ticker cell + offset grid + date column.
    """
    wb = Workbook()
    # Instructions sheet first
    info = wb.active
    info.title = "Instructions"
    instr = [
        ["FactSet Price-Series Formula Generator"],
        [""],
        [f"Method: {method}  |  Lookback: {lookback} td  |  Range: {start}..{end} freq {freq}"],
        [""],
        ["HOW TO USE:"],
    ]
    if method.upper() == "A":
        instr += [
            ["1. Open this workbook in Excel with the FactSet add-in installed."],
            ["2. For each ticker sheet, the formulas in row 2 are time-series FDS calls."],
            ["   They spill DOWN automatically (date, close, volume columns)."],
            ["3. Paste the date formula in A2, close in B2, volume in C2 if not present."],
            ["4. After refresh, export the resulting tidy data and upload in Tab 3."],
        ]
    else:
        instr += [
            ["1. Open in Excel with the FactSet add-in installed."],
            ["2. Put the ticker in cell A2 of each sheet (already populated)."],
            ["3. Column C holds relative-offset price formulas (ROW-based lookback)."],
            ["4. Column D holds explicit-date formulas referencing dates in column B."],
            ["5. Fill column B with dates if using explicit mode; else use column C."],
            ["6. Refresh, then export tidy data and upload in Tab 3."],
        ]
    for r in instr:
        info.append(r)
    info["A1"].font = Font(bold=True, size=14)

    if method.upper() == "A":
        if layout == "stacked":
            ws = wb.create_sheet("AllTickers")
            ws.append(["ticker", "date_formula", "close_formula", "volume_formula"])
            _style_header(ws, 4)
            for t in tickers:
                fs = method_a_timeseries_formulas(t, dictionary, start, end, freq)
                ws.append([t, fs["date"], fs["close"], fs["volume"]])
        else:
            for t in tickers:
                safe = _safe_sheet_name(t)
                ws = wb.create_sheet(safe)
                ws.append(["date", "close", "volume"])
                _style_header(ws, 3)
                fs = method_a_timeseries_formulas(t, dictionary, start, end, freq)
                ws.cell(row=2, column=1, value=fs["date"])
                ws.cell(row=2, column=2, value=fs["close"])
                ws.cell(row=2, column=3, value=fs["volume"])
                for col, w in ((1, 16), (2, 28), (3, 28)):
                    ws.column_dimensions[get_column_letter(col)].width = w
    else:
        for t in tickers:
            safe = _safe_sheet_name(t)
            ws = wb.create_sheet(safe)
            ws.append(["ticker_cell", "date_col_B", "relative_price_C", "explicit_price_D"])
            _style_header(ws, 4)
            ws.cell(row=2, column=1, value=t)  # A2 = ticker
            grid = method_b_offset_grid(dictionary, lookback=lookback, price_metric="price")
            for g in grid:
                r = g["row"]
                ws.cell(row=r, column=3, value=g["relative_formula"])
                ws.cell(row=r, column=4, value=g["explicit_date_formula"])
            for col, w in ((1, 14), (2, 14), (3, 34), (4, 34)):
                ws.column_dimensions[get_column_letter(col)].width = w

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _safe_sheet_name(name: str) -> str:
    bad = set('[]:*?/\\')
    s = "".join("_" if ch in bad else ch for ch in str(name))
    return s[:31] if s else "Sheet"
