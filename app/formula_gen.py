"""FactSet FQL formula generation.

Pure (no web/DB). Replicates the reference ``generate_formula`` exactly and
adds two layout builders plus a downloadable .xlsx builder.

Method A (preferred): per-ticker daily time-series block (date column + close
+ volume) using the corrected comma FQL, rolling from today, e.g.
=FDS("9988-HK","P_PRICE(0D,-250D,D)") and =FDS("9988-HK","P_VOLUME_DAY(0D,-250D,D)").

Method B (fallback): bullet-proof single-date offset grid using 0D-Nd, e.g.
=FDS($A$2,"P_PRICE(0D-"&(ROW()-3)&"D)") and P_VOLUME_DAY likewise.

Date args are COMMA-separated INSIDE the field parentheses (NOT a colon
"start:end:freq" string), most-recent-first (0D, then lookback). Volume uses
P_VOLUME_DAY (not P_VOLUME). ADV (USD) is computed in-app, not pulled.
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
def autodetect_metrics(dictionary: dict) -> Dict[str, str]:
    """Pick smart default price/volume metric keys from a dictionary.

    Price: first key whose name (case-insensitive) contains price/close/px.
    Volume: first key containing volume/vol. Falls back to the first key.
    """
    keys = list((dictionary or {}).get("formulas", {}).keys())
    first = keys[0] if keys else ""

    def _find(substrs: List[str]) -> str:
        for k in keys:
            kl = k.lower()
            if any(s in kl for s in substrs):
                return k
        return first

    return {
        "price_metric": _find(["price", "close", "px"]),
        "volume_metric": _find(["volume", "vol"]),
    }


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
    start: str = "0D",
    end: str = "-250D",
    freq: str = "D",
    price_metric: str = "price",
    volume_metric: str = "volume",
) -> Dict[str, str]:
    """Return the header FDS formulas for a daily date+close+volume block.

    Uses the corrected COMMA FQL form, most-recent-first (start=0D, end=-250D),
    e.g. P_PRICE(0D,-250D,D) and P_VOLUME_DAY(0D,-250D,D). FactSet returns the
    date axis automatically next to the price spill when a time-series formula
    is entered with a date range, so a single formula per series spills down.
    """
    formulas = dictionary.get("formulas", {})
    out: Dict[str, str] = {}
    if price_metric in formulas:
        out["close"] = generate_formula(
            ticker, price_metric, dictionary, start=start, end=end, freq=freq
        )
    else:
        out["close"] = f'=FDS("{ticker}", "P_PRICE({start},{end},{freq})")'
    if volume_metric in formulas:
        out["volume"] = generate_formula(
            ticker, volume_metric, dictionary, start=start, end=end, freq=freq
        )
    else:
        out["volume"] = f'=FDS("{ticker}", "P_VOLUME_DAY({start},{end},{freq})")'
    # date axis helper (best-effort; FactSet also spills the date column next to
    # the price spill automatically).
    out["date"] = f'=FDS("{ticker}", "P_DATE({start},{end},{freq})")'
    return out


# ---------------------------------------------------------------------------
# Method B — offset grid fallback.
# ---------------------------------------------------------------------------
def _fql_root(formulas: dict, metric: str, default: str) -> str:
    """Return the FQL function root (text before the first '(') for a metric."""
    if metric in formulas:
        tmpl = formulas[metric].get("fql_template", default)
        return tmpl.split("(")[0] if "(" in tmpl else tmpl
    return default


def method_b_offset_grid(
    dictionary: dict,
    lookback: int = 250,
    price_metric: str = "price",
    volume_metric: str = "volume",
    ticker_cell: str = "$A$2",
    header_rows: int = 3,
) -> List[Dict[str, Any]]:
    """Return a list of rows describing the bullet-proof offset-grid layout.

    Each row is a self-contained single-date formula using the 0D-Nd offset
    (today minus N trading days), so row 1 = today and rows go further back —
    a rolling window.

    Each row: {row, offset, relative_formula, relative_volume_formula,
               explicit_date_formula}.
    relative price : =FDS($A$2,"P_PRICE(0D-"&(ROW()-3)&"D)")
    relative volume: =FDS($A$2,"P_VOLUME_DAY(0D-"&(ROW()-3)&"D)")
    explicit pattern: =FDS($A$2,"P_PRICE("&B2&")")  (date in column B)
    """
    formulas = dictionary.get("formulas", {})
    base_fql = _fql_root(formulas, price_metric, "P_PRICE")
    vol_fql = _fql_root(formulas, volume_metric, "P_VOLUME_DAY")
    rows: List[Dict[str, Any]] = []
    for i in range(lookback):
        sheet_row = header_rows + 1 + i
        rel = f'=FDS({ticker_cell},"{base_fql}(0D-"&(ROW()-{header_rows})&"D)")'
        rel_vol = f'=FDS({ticker_cell},"{vol_fql}(0D-"&(ROW()-{header_rows})&"D)")'
        exp = f'=FDS({ticker_cell},"{base_fql}("&B{sheet_row}&")")'
        rows.append(
            {
                "row": sheet_row,
                "offset": i,
                "relative_formula": rel,
                "relative_volume_formula": rel_vol,
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
    start: str = "0D",
    end: str = "-250D",
    freq: str = "D",
    layout: str = "per_ticker",  # 'per_ticker' or 'stacked'
    price_metric: str = "price",
    volume_metric: str = "volume",
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
            ["2. For each ticker sheet, the formulas in row 2 are time-series FDS calls"],
            ["   using the corrected COMMA form, e.g. P_PRICE(0D,-250D,D) and"],
            ["   P_VOLUME_DAY(0D,-250D,D). They spill DOWN automatically and FactSet"],
            ["   provides the date column alongside the price spill."],
            ["3. Rolling window: 0D = today / most-recent trading day, looking back"],
            ["   N trading days. Re-pull anytime to refresh to the latest close."],
            ["4. Volume uses P_VOLUME_DAY (NOT P_VOLUME). 20D ADV (USD) is NOT pulled"],
            ["   here — it is computed in-app (Tab 3) from daily price * volume."],
            ["5. After refresh, export the resulting tidy data and upload in Tab 3."],
            [""],
            ["Troubleshooting (no data): use commas not colons inside the field;"],
            ["P_VOLUME_DAY not P_VOLUME; check identifier format (e.g. 9988-HK, BD5CMC);"],
            ["use 0D-first (most-recent-first) order."],
        ]
    else:
        instr += [
            ["1. Open in Excel with the FactSet add-in installed."],
            ["2. Put the ticker in cell A2 of each sheet (already populated)."],
            ["3. Column C holds relative-offset price formulas using the 0D-Nd form,"],
            ["   e.g. P_PRICE(0D-N D); row 1 = today (0D), increasing rows go back."],
            ["4. Column D holds relative-offset volume formulas via P_VOLUME_DAY(0D-N D)."],
            ["5. Column E holds explicit-date price formulas referencing dates in column B;"],
            ["   fill column B with dates if using explicit mode, else use columns C/D."],
            ["6. Rolling window: 0D = today, looking back N trading days. Re-pull anytime"],
            ["   to refresh to the latest close. 20D ADV (USD) is computed in-app (Tab 3)."],
            ["7. Refresh, then export tidy data and upload in Tab 3."],
            [""],
            ["Troubleshooting (no data): use commas not colons inside the field;"],
            ["P_VOLUME_DAY not P_VOLUME; check identifier format (e.g. 9988-HK, BD5CMC);"],
            ["use 0D-first (most-recent-first) order."],
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
                fs = method_a_timeseries_formulas(t, dictionary, start, end, freq,
                                                  price_metric=price_metric,
                                                  volume_metric=volume_metric)
                ws.append([t, fs["date"], fs["close"], fs["volume"]])
        else:
            for t in tickers:
                safe = _safe_sheet_name(t)
                ws = wb.create_sheet(safe)
                ws.append(["date", "close", "volume"])
                _style_header(ws, 3)
                fs = method_a_timeseries_formulas(t, dictionary, start, end, freq,
                                                  price_metric=price_metric,
                                                  volume_metric=volume_metric)
                ws.cell(row=2, column=1, value=fs["date"])
                ws.cell(row=2, column=2, value=fs["close"])
                ws.cell(row=2, column=3, value=fs["volume"])
                for col, w in ((1, 16), (2, 28), (3, 28)):
                    ws.column_dimensions[get_column_letter(col)].width = w
    else:
        for t in tickers:
            safe = _safe_sheet_name(t)
            ws = wb.create_sheet(safe)
            ws.append(["ticker_cell", "date_col_B", "relative_price_C",
                       "relative_volume_D", "explicit_price_E"])
            _style_header(ws, 5)
            ws.cell(row=2, column=1, value=t)  # A2 = ticker
            grid = method_b_offset_grid(dictionary, lookback=lookback,
                                        price_metric=price_metric,
                                        volume_metric=volume_metric)
            for g in grid:
                r = g["row"]
                ws.cell(row=r, column=3, value=g["relative_formula"])
                ws.cell(row=r, column=4, value=g["relative_volume_formula"])
                ws.cell(row=r, column=5, value=g["explicit_date_formula"])
            for col, w in ((1, 14), (2, 14), (3, 34), (4, 34), (5, 34)):
                ws.column_dimensions[get_column_letter(col)].width = w

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _safe_sheet_name(name: str) -> str:
    bad = set('[]:*?/\\')
    s = "".join("_" if ch in bad else ch for ch in str(name))
    return s[:31] if s else "Sheet"
