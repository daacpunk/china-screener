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
import re
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# Reference function — replicated EXACTLY (generalised via kwargs).
# ---------------------------------------------------------------------------
def min_required_bars(params: Dict[str, Any] | None = None, buffer_pct: float = 0.25,
                      hard_floor: int = 90) -> int:
    """Compute the minimum CONTIGUOUS daily depth the screen actually needs.

    Indicators are consecutive-day calcs (Wilder RSI, MACD EMAs, rolling SMA,
    trailing vol window) so dates cannot be skipped — 'only needed dates' means
    the minimum contiguous lookback that warms every indicator. Binding terms:
      - trailing vol window reaching back past Horizon B's start
        (vol_window covers returns; Horizon B reaches day -21)
      - MACD warm-up for STABLE values (~3x slow EMA + signal)
      - RSI warm-up (~3.5x length)
      - the engine's hard min_bars floor
    A safety buffer is added on top, then a sensible hard floor.
    """
    p = dict(params or {})
    vol_window = int(p.get("vol_window", 60))
    h_b_start = int(p.get("horizon_b_start", 21))
    macd_slow = int(p.get("macd_slow", 26))
    macd_signal = int(p.get("macd_signal", 9))
    rsi_length = int(p.get("rsi_length", 14))
    min_bars = int(p.get("min_bars", 60))
    sma_length = int(p.get("sma_length", 20))

    # +1 because returns consume one bar; vol window must sit before latest moves.
    vol_need = vol_window + max(h_b_start, 5) + 1
    macd_need = macd_slow * 3 + macd_signal
    rsi_need = int(rsi_length * 3.5)
    base = max(min_bars, vol_need, macd_need, rsi_need, sma_length)
    depth = int(round(base * (1.0 + buffer_pct)))
    return max(hard_floor, depth)


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
    end: str = "-150D",
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


def method_a_grid(
    ticker: str,
    dictionary: dict,
    lookback: int = 150,
    price_metric: str = "price",
    volume_metric: str = "volume",
    header_rows: int = 1,
    include_date: bool = False,
) -> List[Dict[str, Any]]:
    """Explicit row-per-day grid for one ticker (no array-spill dependency).

    Each trading day gets its own self-contained single-date FDS formula for
    date, close and volume using the 0D-Nd offset (today minus N trading days):
      row 1 (offset 0) = today (0D), row 2 = -1D, ... row N = -(N-1)D.
    This ALWAYS returns a full time series regardless of the FactSet add-in's
    dynamic-array support. Identifier is embedded directly in each formula so
    each sheet is self-contained.

    date  : =FDS("T","P_DATE(0D-N D)")        (best-effort; see note)
    close : =FDS("T","P_PRICE(0D-N D)")
    volume: =FDS("T","P_VOLUME_DAY(0D-N D)")
    """
    formulas = dictionary.get("formulas", {})
    price_fql = _fql_root(formulas, price_metric, "P_PRICE")
    vol_fql = _fql_root(formulas, volume_metric, "P_VOLUME_DAY")
    date_fql = _fql_root(formulas, "date_point", "P_DATE")
    rows: List[Dict[str, Any]] = []
    for i in range(lookback):
        off = f"0D-{i}D" if i else "0D"
        entry = {
            "row": header_rows + 1 + i,
            "offset": i,
            "close_formula": f'=FDS("{ticker}","{price_fql}({off})")',
            "volume_formula": f'=FDS("{ticker}","{vol_fql}({off})")',
        }
        # Date column is optional: dropping it removes ~1/3 of FDS calls. Dates
        # are reconstructed in-app from row order (row 1 = latest trading day).
        if include_date:
            entry["date_formula"] = f'=FDS("{ticker}","{date_fql}({off})")'
        rows.append(entry)
    return rows


# ---------------------------------------------------------------------------
# Spilling per-ticker layout — the fast default for Method A.
# ---------------------------------------------------------------------------
def method_a_spill_formulas(
    dictionary: dict,
    lookback: int = 109,
    price_metric: str = "price",
    volume_metric: str = "volume",
    ticker_cell: str = "A2",
) -> Dict[str, str]:
    """Return ONE spilling range FDS formula per series, referencing a ticker CELL.

    The FactSet add-in spills a single date-range formula down its column, so we
    emit ~2-3 calls/ticker (date + price + volume) instead of one call per cell.

    Verified against the user's live FactSet add-in:
      - Reference the ticker CELL (A2), NOT an embedded literal string:
            =FDS(A2,"P_PRICE(0,-109D,D)")
      - Start anchor is ``0`` (NOT ``0D``): ``(0,-<N>D,D)``.
      - The date axis uses JULIAN on the price series' .dates accessor:
            =FDS(A2,"JULIAN(P_PRICE(0,-109D,D).dates)")
      - These MUST be written as dynamic-array (spilling) formulas so Excel does
        not prepend the implicit-intersection ``@`` (which would force a single
        value and kill the spill). See _write_spill_formula / array markup.

    Column convention on each ticker's own sheet: B=date, C=close, D=volume,
    with the ticker literal in A2.

    FQL roots come from the active dictionary's templates (via _fql_root) so
    custom dictionaries work.

    Returns a dict with keys 'date', 'close', 'volume' (formulas as strings).
    """
    formulas = dictionary.get("formulas", {})
    price_fql = _fql_root(formulas, price_metric, "P_PRICE")
    vol_fql = _fql_root(formulas, volume_metric, "P_VOLUME_DAY")
    rng = f"0,-{lookback}D,D"
    price_expr = f"{price_fql}({rng})"
    return {
        "date": f'=FDS({ticker_cell},"JULIAN({price_expr}.dates)")',
        "close": f'=FDS({ticker_cell},"{price_expr}")',
        "volume": f'=FDS({ticker_cell},"{vol_fql}({rng})")',
    }


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
    lookback: int = 150,
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
    lookback: int = 150,
    start: str = "0D",
    end: str = "-150D",
    freq: str = "D",
    layout: str = "spill",  # 'spill' (default) | 'per_ticker' | 'stacked'
    price_metric: str = "price",
    volume_metric: str = "volume",
    include_date: bool = False,
    batch_note: str = "",
) -> bytes:
    """Build the formula workbook as xlsx bytes.

    Method A:
      - spill (DEFAULT): one sheet per ticker; A2 = ticker literal and a SINGLE
        spilling range formula per series (price/volume, + date if requested)
        in row 2. The add-in fills the whole column — ~2 calls/ticker.
      - per_ticker: one sheet per ticker with an explicit row-per-day grid
        (no spill dependency; one self-contained =FDS per trading day).
      - stacked: a single Instructions sheet + one tidy-long sheet (all tickers).
    Method B:
      - one sheet per ticker with ticker cell + offset grid + date column.

    ``batch_note`` (when set) is added to the Instructions sheet, e.g.
    "Batch 1 of 8 — tickers AAA..ZZZ".
    """
    wb = Workbook()
    # Instructions sheet first
    info = wb.active
    info.title = "Instructions"
    instr = [
        ["FactSet Price-Series Formula Generator"],
        [""],
        [f"Method: {method}  |  Lookback: {lookback} td  |  Range: {start}..{end} freq {freq}"],
    ]
    if batch_note:
        instr += [[batch_note]]
    instr += [
        [""],
        ["HOW TO USE:"],
    ]
    if method.upper() == "A" and layout == "spill":
        instr += [
            ["1. Open this workbook in Excel with the FactSet add-in installed."],
            ["2. Each ticker is on its OWN sheet. A2 holds the ticker; the spill"],
            ["   formulas in row 2 REFERENCE A2 and fill the whole column down:"],
            ["     B2 = date, C2 = close, D2 = volume."],
            [f"3. Formulas (entered as dynamic-array / spilling, N={lookback}):"],
            [f'     B2: =FDS(A2,"JULIAN(P_PRICE(0,-{lookback}D,D).dates)")'],
            [f'     C2: =FDS(A2,"P_PRICE(0,-{lookback}D,D)")'],
            [f'     D2: =FDS(A2,"P_VOLUME_DAY(0,-{lookback}D,D)")'],
            ["   One formula per series fills the whole column (~3 calls/ticker"],
            ["   instead of one per cell)."],
            ["4. Start anchor is 0 (NOT 0D); range is most-recent-first; volume uses"],
            ["   P_VOLUME_DAY (NOT P_VOLUME); the ticker is a CELL reference (A2),"],
            ["   NOT a quoted literal."],
            ["5. These are written as spilling (dynamic-array) formulas so Excel does"],
            ["   NOT prepend '@'. Make sure nothing blocks the spill (keep the cells"],
            ["   below/right of B2:D2 empty)."],
            ["6. 20D ADV (USD) is NOT pulled here — it is computed in-app (Tab 3) from"],
            ["   daily price * volume."],
            ["7. After refresh, upload the sheet(s) or export tidy long and upload in"],
            ["   Tab 3. Tab 3 forward-fills the single A2 ticker down the spilled rows."],
            [""],
            ["Troubleshooting (no data / single value): if you see '@FDS', the spill"],
            ["was blocked — clear cells under the formula and re-enter. Use commas not"],
            ["colons; P_VOLUME_DAY not P_VOLUME; identifier in A2 (e.g. 9988-HK, BD5CMC)."],
        ]
    elif method.upper() == "A":
        instr += [
            ["1. Open this workbook in Excel with the FactSet add-in installed."],
            [f"2. Each ticker sheet has an EXPLICIT row-per-day grid: {lookback} rows,"],
            ["   one self-contained =FDS formula per trading day for date / close /"],
            ["   volume. This does NOT rely on array-spill, so a full time series"],
            ["   always returns (one value per row)."],
            ["3. Row 1 (offset 0D) = today / most-recent trading day; each row below"],
            ["   goes one trading day further back (0D-1D, 0D-2D, ...). Rolling: re-pull"],
            ["   anytime to refresh to the latest close."],
            ["4. Formulas: close = P_PRICE(0D-N D), volume = P_VOLUME_DAY(0D-N D),"],
            ["   date = P_DATE(0D-N D). Volume uses P_VOLUME_DAY (NOT P_VOLUME)."],
            ["5. 20D ADV (USD) is NOT pulled here — it is computed in-app (Tab 3) from"],
            ["   daily price * volume."],
            ["6. After refresh, export the resulting tidy data and upload in Tab 3."],
            ["   (Stacked layout = a single 'AllTickers' sheet in tidy long format:"],
            ["   columns ticker/date/close/volume, one row per ticker per day — also"],
            ["   explicit per-row formulas, no spill. Upload that sheet directly.)"],
            [""],
            ["Note: if P_DATE returns blank in your entitlement, the close/volume"],
            ["columns still work; dates can be reconstructed from the row offset (row 1"],
            ["= latest trading day) or pull dates via Method B's explicit-date column."],
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
        if layout == "spill":
            # Spilling layout: each ticker on its OWN sheet (no collision).
            # A2 = ticker literal; the spill formulas REFERENCE A2 and sit in row
            # 2: B2=date (JULIAN ...dates), C2=price, D2=volume. Each is written as
            # a DYNAMIC-ARRAY formula so Excel does not prepend the implicit-
            # intersection '@' (which would force a single value and kill spill).
            from openpyxl.worksheet.formula import ArrayFormula
            for t in tickers:
                safe = _safe_sheet_name(t)
                ws = wb.create_sheet(safe)
                ws.append(["ticker", "date", "close", "volume"])
                _style_header(ws, 4)
                spill = method_a_spill_formulas(
                    dictionary, lookback=lookback,
                    price_metric=price_metric, volume_metric=volume_metric,
                    ticker_cell="A2")
                ws.cell(row=2, column=1, value=t)  # A2 = ticker literal
                # Dynamic-array (spilling) formulas anchored at their own cell.
                ws.cell(row=2, column=2, value=ArrayFormula("B2", spill["date"]))
                ws.cell(row=2, column=3, value=ArrayFormula("C2", spill["close"]))
                ws.cell(row=2, column=4, value=ArrayFormula("D2", spill["volume"]))
                for col, w in ((1, 14), (2, 16), (3, 30), (4, 32)):
                    ws.column_dimensions[get_column_letter(col)].width = w
        elif layout == "stacked":
            # Tidy LONG format: one row per (ticker, trading day) with explicit
            # single-date formulas (no array-spill). This is exactly the shape
            # Tab 3 ingests, all tickers stacked in a single sheet.
            ws = wb.create_sheet("AllTickers")
            header = (["ticker", "date", "close", "volume"] if include_date
                      else ["ticker", "close", "volume"])
            ws.append(header)
            _style_header(ws, len(header))
            for t in tickers:
                grid = method_a_grid(t, dictionary, lookback=lookback,
                                     price_metric=price_metric,
                                     volume_metric=volume_metric,
                                     include_date=include_date)
                for g in grid:
                    if include_date:
                        ws.append([t, g["date_formula"], g["close_formula"], g["volume_formula"]])
                    else:
                        ws.append([t, g["close_formula"], g["volume_formula"]])
            widths = ((1, 14), (2, 24), (3, 30), (4, 32)) if include_date else ((1, 14), (2, 30), (3, 32))
            for col, w in widths:
                ws.column_dimensions[get_column_letter(col)].width = w
        else:
            for t in tickers:
                safe = _safe_sheet_name(t)
                ws = wb.create_sheet(safe)
                header = ["date", "close", "volume"] if include_date else ["close", "volume"]
                ws.append(header)
                _style_header(ws, len(header))
                # Explicit row-per-day grid: one self-contained FDS formula per
                # trading day. No reliance on array-spill, so a full ~N-day time
                # series always returns. Row 2 = today, row 3 = -1D, ...
                grid = method_a_grid(t, dictionary, lookback=lookback,
                                     price_metric=price_metric,
                                     volume_metric=volume_metric,
                                     include_date=include_date)
                for g in grid:
                    r = g["row"]
                    if include_date:
                        ws.cell(row=r, column=1, value=g["date_formula"])
                        ws.cell(row=r, column=2, value=g["close_formula"])
                        ws.cell(row=r, column=3, value=g["volume_formula"])
                    else:
                        ws.cell(row=r, column=1, value=g["close_formula"])
                        ws.cell(row=r, column=2, value=g["volume_formula"])
                widths = ((1, 22), (2, 30), (3, 32)) if include_date else ((1, 30), (2, 32))
                for col, w in widths:
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
    return _strip_empty_formula_values(bio.getvalue())


def _chunk(seq: List[Any], size: int) -> List[List[Any]]:
    size = max(1, int(size))
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def build_formula_workbooks_batched(
    tickers: List[str],
    dictionary: dict,
    method: str = "A",
    lookback: int = 150,
    start: str = "0D",
    end: str = "-150D",
    freq: str = "D",
    layout: str = "spill",
    price_metric: str = "price",
    volume_metric: str = "volume",
    include_date: bool = False,
    batch_size: int = 75,
) -> List[tuple]:
    """Split ``tickers`` into chunks of ``batch_size`` and build one workbook per
    chunk. Returns a list of ``(filename, xlsx_bytes)`` tuples.

    Each workbook is a full standalone file (its own Instructions sheet noting
    'Batch k of M — tickers X..Y'). ``_strip_empty_formula_values`` runs on every
    workbook (inside ``build_formula_workbook``) so none trigger Excel's repair
    prompt. Filenames: ``factset_formulas_method_A_batch_01_of_08.xlsx`` etc.
    """
    chunks = _chunk(list(tickers), batch_size)
    total = len(chunks)
    width = max(2, len(str(total)))
    out: List[tuple] = []
    for idx, chunk in enumerate(chunks, start=1):
        first, last = chunk[0], chunk[-1]
        note = f"Batch {idx} of {total} — tickers {first}..{last} ({len(chunk)} names)"
        data = build_formula_workbook(
            chunk, dictionary, method=method, lookback=lookback,
            start=start, end=end, freq=freq, layout=layout,
            price_metric=price_metric, volume_metric=volume_metric,
            include_date=include_date, batch_note=note,
        )
        fname = (f"factset_formulas_method_{method}_batch_"
                 f"{idx:0{width}d}_of_{total:0{width}d}.xlsx")
        out.append((fname, data))
    return out


def zip_workbooks(files: List[tuple]) -> bytes:
    """Assemble a list of ``(filename, bytes)`` into a single in-memory zip."""
    import zipfile

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, data in files:
            zf.writestr(fname, data)
    return bio.getvalue()


def _strip_empty_formula_values(xlsx_bytes: bytes) -> bytes:
    """Remove empty cached-value elements (``<v/>``) that openpyxl writes after
    every formula cell.

    openpyxl emits ``<f>FORMULA</f><v/>`` for formula cells. An empty-but-present
    cached value on a formula that references an add-in function not yet loaded
    (``FDS``) makes Excel report 'We found a problem with some content...' and
    offer to repair on open. Stripping the empty ``<v/>`` yields a clean
    ``<f>FORMULA</f>`` cell that Excel opens without complaint and recalculates
    once the FactSet add-in is present. The XML stays well-formed.
    """
    import zipfile

    zin = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("xl/worksheets/") and item.filename.endswith(".xml"):
                txt = data.decode("utf-8")
                txt = txt.replace("</f><v/>", "</f>").replace("</f><v />", "</f>")
                # Upgrade legacy array formulas to DYNAMIC-array (spilling) form so
                # modern Excel does NOT prepend the implicit-intersection '@'
                # (which forces a single value and kills the FactSet spill).
                # Excel marks a spilling formula with aca="1" ca="1".
                txt = re.sub(
                    r'<f t="array" ref="([^"]+)">',
                    r'<f t="array" ref="\1" aca="1" ca="1">',
                    txt,
                )
                data = txt.encode("utf-8")
            zout.writestr(item, data)
    return out.getvalue()


def _safe_sheet_name(name: str) -> str:
    bad = set('[]:*?/\\')
    s = "".join("_" if ch in bad else ch for ch in str(name))
    return s[:31] if s else "Sheet"
