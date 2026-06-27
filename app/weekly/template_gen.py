"""Phase D weekly FactSet template generator.

Builds a downloadable .xlsx using the proven spill / text-formula + ActivateSpills
VBA approach (the exact pattern in app/formula_gen.py). One sheet per ticker:

    A2 = FactSet ticker literal
    B2 = =FDS(A2,"JULIAN(P_PRICE(0,-{depth}D,D).dates)")   (JULIAN dates)
    C2 = =FDS(A2,"P_PRICE(0,-{depth}D,D)")                  (close, spills)
    D2 = =FDS(A2,"P_VOLUME_DAY(0,-{depth}D,D)")             (volume, spills)

The HSI benchmark series is pulled ONCE on a dedicated "HSI" sheet, using the
FactSet identifier 180458 as a literal in the formula (NOT a cell reference, so
it survives even if the sheet is reordered):

    B2 = =FDS("180458","JULIAN(P_PRICE(0,-{depth}D,D).dates)")
    C2 = =FDS("180458","P_PRICE(0,-{depth}D,D)")

depth is a FIXED safe floor of 300 trading days. 300 td ~= 14 calendar months,
which always covers YTD (max ~252 td) plus the 60D context volatility window
(252 + 60 = 312 only at year-end; the YTD anchor is the most recent year-start,
which is at most ~252 td back, and 6M=126 + 60D=186, so 300 covers every
headline + context window with comfortable margin while keeping ~3 FDS calls
per ticker).

Formulas are stored as TEXT (leading data_type='s') so Excel does not inject the
implicit-intersection '@' on open; the ActivateSpills macro on the Instructions
sheet re-enters them via .Formula2 so they spill. A Manifest sheet lists every
column, its FDS formula, and the depth. Batched into a ZIP at >75 tickers.

Pure (no web / DB). Reuses formula_gen._strip_empty_formula_values / zip helper.
"""
from __future__ import annotations

import io
from typing import Any, Dict, List, Tuple

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .. import formula_gen as fg
from . import HSI_FACTSET_ID

# Fixed safe floor: 300 trading days always covers YTD + 60D context window.
DEPTH = 300
BATCH_SIZE = 75


def _price_expr(depth: int) -> str:
    return f"P_PRICE(0,-{depth}D,D)"


def _vol_expr(depth: int) -> str:
    return f"P_VOLUME_DAY(0,-{depth}D,D)"


def ticker_formulas(ticker_cell: str = "A2", depth: int = DEPTH) -> Dict[str, str]:
    """Per-ticker spill formulas referencing the ticker CELL (A2)."""
    pe = _price_expr(depth)
    return {
        "date": f'=FDS({ticker_cell},"JULIAN({pe}.dates)")',
        "close": f'=FDS({ticker_cell},"{pe}")',
        "volume": f'=FDS({ticker_cell},"{_vol_expr(depth)}")',
    }


def hsi_formulas(depth: int = DEPTH) -> Dict[str, str]:
    """HSI benchmark spill formulas, using the 180458 identifier as a LITERAL."""
    pe = _price_expr(depth)
    return {
        "date": f'=FDS("{HSI_FACTSET_ID}","JULIAN({pe}.dates)")',
        "close": f'=FDS("{HSI_FACTSET_ID}","{pe}")',
    }


_INSTRUCTIONS_HEADER = "Weekly Quant One-Pager — FactSet Template (Phase D)"


def _instructions_rows(depth: int, n_tickers: int, batch_note: str = "") -> List[List[str]]:
    tf = ticker_formulas("A2", depth)
    hf = hsi_formulas(depth)
    rows: List[List[str]] = [
        [_INSTRUCTIONS_HEADER],
        [""],
        [f"Depth: {depth} trading days (fixed floor — covers YTD + 60D vol window)."],
        [f"Tickers in this file: {n_tickers}.  HSI benchmark id: {HSI_FACTSET_ID}."],
    ]
    if batch_note:
        rows += [[batch_note]]
    rows += [
        [""],
        ["SPILL LAYOUT — formulas are stored as TEXT so Excel doesn't add the"],
        ["'@' implicit-intersection on open. Run the ONE-CLICK macro below once"],
        ["to activate every sheet's spills (it re-enters each formula via"],
        [".Formula2, exactly as if you typed it — so they spill, no '@')."],
        [""],
        ["STEP 1 — Activate the spills (one time):"],
        ["  a) Open this workbook in Excel with the FactSet add-in installed."],
        ["  b) Press Option+F11 (Mac) / Alt+F11 (Win) to open the VBA editor."],
        ["  c) Insert > Module, paste the macro below, press F5 (or Run)."],
        ["  d) Close the editor. Every sheet now has LIVE spilling formulas."],
        [""],
        ["STEP 2 — Let FactSet refresh, then upload the workbook in the Weekly"],
        ["  Note tab (it reads each ticker sheet + the HSI sheet, decodes the"],
        ["  JULIAN dates, and computes all metrics in-app)."],
        [""],
        ["---------- COPY THIS MACRO ----------"],
        ["Sub ActivateSpills()"],
        ["  Dim ws As Worksheet, c As Range, cols As Variant, i As Integer"],
        ["  cols = Array(2, 3, 4)   ' B=date, C=close, D=volume"],
        ["  For Each ws In ThisWorkbook.Worksheets"],
        ['    If ws.Name <> "Instructions" And ws.Name <> "Manifest" Then'],
        ["      For i = LBound(cols) To UBound(cols)"],
        ["        Set c = ws.Cells(2, cols(i))"],
        ['        If Left(c.Text, 1) = "=" Then'],
        ["          Dim f As String: f = c.Text"],
        ['          c.Value = ""            ' + "' clear the text"],
        ["          c.Formula2 = f          " + "' enter as dynamic array (spills)"],
        ["        End If"],
        ["      Next i"],
        ["    End If"],
        ["  Next ws"],
        ["End Sub"],
        ["---------- END MACRO ----------"],
        [""],
        [f"Per-ticker formulas (N={depth}, A2 = FactSet ticker):"],
        [f"  B2: {tf['date']}"],
        [f"  C2: {tf['close']}"],
        [f"  D2: {tf['volume']}"],
        [""],
        ["HSI benchmark sheet (pulled once):"],
        [f"  B2: {hf['date']}"],
        [f"  C2: {hf['close']}"],
        [""],
        ["~3 calls per ticker + 2 for HSI. Volume uses P_VOLUME_DAY. All returns,"],
        ["volatility, momentum, and HSI-relative metrics are computed IN-APP."],
        [""],
        ["No macros? Manual fallback: click C2, press F2 then Enter to re-enter"],
        ["the formula (it will spill); repeat for B2/D2 on each sheet."],
    ]
    return rows


def _manifest_rows(tickers: List[str], depth: int) -> List[List[str]]:
    tf = ticker_formulas("A2", depth)
    hf = hsi_formulas(depth)
    rows = [
        ["sheet", "column", "field", "fds_formula", "depth_td"],
        ["<each ticker>", "A", "ticker", "(literal in A2)", depth],
        ["<each ticker>", "B", "date (JULIAN)", tf["date"], depth],
        ["<each ticker>", "C", "close", tf["close"], depth],
        ["<each ticker>", "D", "volume", tf["volume"], depth],
        ["HSI", "A", "identifier", HSI_FACTSET_ID, depth],
        ["HSI", "B", "date (JULIAN)", hf["date"], depth],
        ["HSI", "C", "close", hf["close"], depth],
        ["", "", "", "", ""],
        ["Tickers in this file:", "", "", "", len(tickers)],
    ]
    for t in tickers:
        rows.append([t, "", "", "", ""])
    return rows


def build_weekly_template(
    tickers: List[str],
    depth: int = DEPTH,
    batch_note: str = "",
) -> bytes:
    """Build a single weekly-template workbook (Instructions + Manifest + HSI +
    one sheet per ticker) as xlsx bytes. Formulas stored as TEXT; spill metadata
    added via the shared _strip_empty_formula_values pass."""
    depth = max(int(depth or DEPTH), DEPTH)
    wb = Workbook()

    # Instructions sheet (first).
    info = wb.active
    info.title = "Instructions"
    for r in _instructions_rows(depth, len(tickers), batch_note):
        info.append(r)
    info["A1"].font = Font(bold=True, size=14)

    # HSI benchmark sheet (pulled once, literal identifier).
    hsi = wb.create_sheet("HSI")
    hsi.append(["identifier", "date", "close"])
    fg._style_header(hsi, 3)
    hf = hsi_formulas(depth)
    hsi.cell(row=2, column=1, value=HSI_FACTSET_ID)
    for col, key in ((2, "date"), (3, "close")):
        c = hsi.cell(row=2, column=col, value=hf[key])
        c.data_type = "s"
    for col, w in ((1, 14), (2, 16), (3, 30)):
        hsi.column_dimensions[get_column_letter(col)].width = w

    # Per-ticker sheets.
    used_names = {"instructions", "hsi", "manifest"}
    for t in tickers:
        base = fg._safe_sheet_name(t)
        safe = base
        suffix = 1
        while safe.lower() in used_names:
            tail = f"_{suffix}"
            safe = base[: 31 - len(tail)] + tail
            suffix += 1
        used_names.add(safe.lower())
        ws = wb.create_sheet(safe)
        ws.append(["ticker", "date", "close", "volume"])
        fg._style_header(ws, 4)
        tf = ticker_formulas("A2", depth)
        ws.cell(row=2, column=1, value=t)  # A2 = ticker literal
        for col, key in ((2, "date"), (3, "close"), (4, "volume")):
            c = ws.cell(row=2, column=col, value=tf[key])
            c.data_type = "s"
        for col, w in ((1, 14), (2, 16), (3, 30), (4, 32)):
            ws.column_dimensions[get_column_letter(col)].width = w

    # Manifest sheet (auditable).
    man = wb.create_sheet("Manifest")
    for r in _manifest_rows(tickers, depth):
        man.append(r)
    fg._style_header(man, 5)
    for col, w in ((1, 22), (2, 8), (3, 16), (4, 44), (5, 10)):
        man.column_dimensions[get_column_letter(col)].width = w

    bio = io.BytesIO()
    wb.save(bio)
    # Reuse the proven cleanup that strips empty cached values and marks the
    # single-FDS spill cells as dynamic arrays.
    return fg._strip_empty_formula_values(bio.getvalue())


def build_weekly_templates_batched(
    tickers: List[str],
    depth: int = DEPTH,
    batch_size: int = BATCH_SIZE,
) -> List[Tuple[str, bytes]]:
    """Split into chunks of ``batch_size`` and build one standalone workbook per
    chunk (each carries its own HSI sheet). Returns [(filename, bytes), ...]."""
    chunks = fg._chunk(list(tickers), batch_size)
    total = len(chunks)
    width = max(2, len(str(total)))
    out: List[Tuple[str, bytes]] = []
    for idx, chunk in enumerate(chunks, start=1):
        first, last = chunk[0], chunk[-1]
        note = f"Batch {idx} of {total} — tickers {first}..{last} ({len(chunk)} names)"
        data = build_weekly_template(chunk, depth=depth, batch_note=note)
        fname = f"weekly_template_batch_{idx:0{width}d}_of_{total:0{width}d}.xlsx"
        out.append((fname, data))
    return out


def zip_templates(files: List[Tuple[str, bytes]]) -> bytes:
    return fg.zip_workbooks(files)
