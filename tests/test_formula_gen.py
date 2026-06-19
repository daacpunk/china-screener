"""generate_formula + BOTH formula-layout generators + xlsx builder.

Corrected FQL: comma-separated date args INSIDE the field parentheses,
most-recent-first (0D,-250D,D); volume via P_VOLUME_DAY; Method B uses the
bullet-proof 0D-Nd single-date offset.
"""
import io
import json
from pathlib import Path

import openpyxl

from app import formula_gen as fg

DICT = {
    "formulas": {
        "price": {"fql_template": "P_PRICE({start},{end},{freq})"},
        "volume": {"fql_template": "P_VOLUME_DAY({start},{end},{freq})"},
    }
}


def test_generate_formula_basic():
    out = fg.generate_formula("9988-HK", "price", DICT, start="0D", end="-250D", freq="D")
    assert out == '=FDS("9988-HK", "P_PRICE(0D,-250D,D)")'
    # commas, not colons
    assert ":" not in out


def test_generate_formula_unknown_metric():
    out = fg.generate_formula("X", "nope", DICT)
    assert out.startswith("# ERROR: Unknown metric")


def test_generate_formula_partial_placeholders():
    # only some placeholders provided -> others left intact
    out = fg.generate_formula("X", "price", DICT, start="0D")
    assert "0D" in out and "{end}" in out


def test_method_a_timeseries():
    a = fg.method_a_timeseries_formulas("9988-HK", DICT, start="0D", end="-250D", freq="D")
    assert a["close"] == '=FDS("9988-HK", "P_PRICE(0D,-250D,D)")'
    assert a["volume"] == '=FDS("9988-HK", "P_VOLUME_DAY(0D,-250D,D)")'
    # comma form, NO colon
    assert "0D,-250D,D" in a["close"]
    assert "0D:-250D:D" not in a["close"]
    assert ":" not in a["close"] and ":" not in a["volume"]
    # volume uses P_VOLUME_DAY
    assert "P_VOLUME_DAY" in a["volume"]
    assert "P_DATE" in a["date"]


def test_method_a_defaults_rolling_from_today():
    # Defaults should be the rolling-from-today window.
    a = fg.method_a_timeseries_formulas("9988-HK", DICT)
    assert a["close"] == '=FDS("9988-HK", "P_PRICE(0D,-150D,D)")'
    assert a["volume"] == '=FDS("9988-HK", "P_VOLUME_DAY(0D,-150D,D)")'


def test_method_b_offset_grid():
    grid = fg.method_b_offset_grid(DICT, lookback=10, ticker_cell="$A$2", header_rows=3)
    assert len(grid) == 10
    first = grid[0]
    assert first["row"] == 4 and first["offset"] == 0
    # 0D-Nd offset form for price and volume
    assert first["relative_formula"] == '=FDS($A$2,"P_PRICE(0D-"&(ROW()-3)&"D)")'
    assert first["relative_volume_formula"] == '=FDS($A$2,"P_VOLUME_DAY(0D-"&(ROW()-3)&"D)")'
    assert "0D-" in first["relative_formula"]
    assert "P_VOLUME_DAY" in first["relative_volume_formula"]
    # explicit pattern references column B for the row
    assert first["explicit_date_formula"] == '=FDS($A$2,"P_PRICE("&B4&")")'


def test_build_workbook_method_a_opens():
    # Method A per-ticker now writes an EXPLICIT row-per-day grid (no array spill).
    data = fg.build_formula_workbook(["9988-HK", "PDD-CN"], DICT, method="A",
                                     layout="per_ticker", lookback=150)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "Instructions" in wb.sheetnames
    assert "9988-HK" in wb.sheetnames
    ws = wb["9988-HK"]
    assert ws.cell(row=1, column=1).value == "date"
    # Row 2 = today (0D); row 3 = 0D-1D; full grid = 150 data rows.
    close2 = str(ws.cell(row=2, column=2).value)
    close3 = str(ws.cell(row=3, column=2).value)
    volume2 = str(ws.cell(row=2, column=3).value)
    assert 'P_PRICE(0D)' in close2
    assert 'P_PRICE(0D-1D)' in close3
    assert "P_VOLUME_DAY" in volume2
    assert ws.max_row == 1 + 150  # header + 150 daily rows
    # No colon form anywhere
    assert ":" not in close2 and ":" not in close3


def test_method_a_grid_row_per_day():
    grid = fg.method_a_grid("9988-HK", DICT, lookback=5)
    assert len(grid) == 5
    # row 1 = today (0D), row 2 = 0D-1D, ...
    assert grid[0]["close_formula"] == '=FDS("9988-HK","P_PRICE(0D)")'
    assert grid[1]["close_formula"] == '=FDS("9988-HK","P_PRICE(0D-1D)")'
    assert grid[0]["volume_formula"] == '=FDS("9988-HK","P_VOLUME_DAY(0D)")'
    assert grid[4]["close_formula"] == '=FDS("9988-HK","P_PRICE(0D-4D)")'
    # no colon range form anywhere
    assert all(":" not in g["close_formula"] for g in grid)


def test_build_workbook_method_a_stacked():
    # Stacked = tidy LONG format: one row per (ticker, day) with explicit
    # single-date formulas (no array-spill). Tab-3 ingestible.
    data = fg.build_formula_workbook(["AAA", "BBB"], DICT, method="A",
                                     layout="stacked", lookback=10)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "AllTickers" in wb.sheetnames
    ws = wb["AllTickers"]
    assert [c.value for c in ws[1]] == ["ticker", "date", "close", "volume"]
    # header + 2 tickers * 10 days = 21 rows
    assert ws.max_row == 1 + 2 * 10
    # first ticker block: row 2 = AAA today, explicit single-date formula
    assert ws.cell(row=2, column=1).value == "AAA"
    assert ws.cell(row=2, column=3).value == '=FDS("AAA","P_PRICE(0D)")'
    assert ws.cell(row=3, column=3).value == '=FDS("AAA","P_PRICE(0D-1D)")'
    # second ticker block starts at row 12
    assert ws.cell(row=12, column=1).value == "BBB"
    assert ws.cell(row=12, column=3).value == '=FDS("BBB","P_PRICE(0D)")'
    # no colon range form anywhere in the close column
    for r in range(2, ws.max_row + 1):
        assert ":" not in str(ws.cell(row=r, column=3).value)


def test_build_workbook_method_b_opens():
    data = fg.build_formula_workbook(["9988-HK"], DICT, method="B", lookback=20)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb["9988-HK"]
    assert ws.cell(row=2, column=1).value == "9988-HK"  # A2 = ticker
    price = str(ws.cell(row=4, column=3).value)
    volume = str(ws.cell(row=4, column=4).value)
    # 0D-Nd offset form, P_VOLUME_DAY for volume
    assert "ROW()" in price and "0D-" in price
    assert "P_VOLUME_DAY" in volume and "0D-" in volume


# ---- bundled sample dictionary: corrected templates ----
def test_sample_dictionary_corrected_templates():
    p = Path(__file__).resolve().parent.parent / "sample_data" / "dictionary.json"
    data = json.loads(p.read_text())
    formulas = data["formulas"]
    assert data["version"] == "2.0.0"
    # price template: commas not colons
    price_tmpl = formulas["price"]["fql_template"]
    assert price_tmpl == "P_PRICE({start},{end},{freq})"
    assert ":" not in price_tmpl
    # volume uses P_VOLUME_DAY
    vol_tmpl = formulas["volume"]["fql_template"]
    assert "P_VOLUME_DAY" in vol_tmpl
    assert ":" not in vol_tmpl
    # no fake P_ADV_USD field in any fql_template (notes may mention it)
    all_templates = " ".join(v["fql_template"] for v in formulas.values())
    assert "P_ADV_USD" not in all_templates
    # corrected GICS field names
    assert formulas["sector"]["fql_template"].startswith("FG_GICS_SECTOR")
    assert "FG_GICS_SUB_IND" in formulas["sub_industry"]["fql_template"]


def test_sample_dictionary_generates_corrected_price():
    p = Path(__file__).resolve().parent.parent / "sample_data" / "dictionary.json"
    data = json.loads(p.read_text())
    out = fg.generate_formula("9988-HK", "price", data, start="0D", end="-250D", freq="D")
    assert out == '=FDS("9988-HK", "P_PRICE(0D,-250D,D)")'


# ---- ITEM 4: configurable price/volume metric keys ----
DICT_CUSTOM = {
    "formulas": {
        "px_last": {"fql_template": "PX_LAST({start},{end},{freq})"},
        "vol": {"fql_template": "VOL_TRADED({start},{end},{freq})"},
    }
}


def test_autodetect_metrics_custom_keys():
    auto = fg.autodetect_metrics(DICT_CUSTOM)
    assert auto["price_metric"] == "px_last"  # contains 'px'
    assert auto["volume_metric"] == "vol"     # contains 'vol'


def test_workbook_honors_custom_metric_keys():
    # Without configurable keys this fell back to generic P_PRICE/P_VOLUME_DAY.
    data = fg.build_formula_workbook(
        ["9988-HK"], DICT_CUSTOM, method="A", layout="per_ticker",
        price_metric="px_last", volume_metric="vol",
    )
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb["9988-HK"]
    close = str(ws.cell(row=2, column=2).value)
    volume = str(ws.cell(row=2, column=3).value)
    # The user's fql_template root is used, NOT the generic fallback (grid form).
    assert "PX_LAST(0D)" in close
    assert "P_PRICE" not in close
    assert "VOL_TRADED(0D)" in volume
    assert "P_VOLUME" not in volume


def test_method_b_honors_custom_price_metric():
    grid = fg.method_b_offset_grid(DICT_CUSTOM, lookback=5, price_metric="px_last", volume_metric="vol")
    assert "PX_LAST" in grid[0]["relative_formula"]
    assert "P_PRICE" not in grid[0]["relative_formula"]
    assert "VOL_TRADED" in grid[0]["relative_volume_formula"]
