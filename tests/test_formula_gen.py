"""generate_formula + BOTH formula-layout generators + xlsx builder."""
import io

import openpyxl

from app import formula_gen as fg

DICT = {
    "formulas": {
        "price": {"fql_template": "P_PRICE({start}:{end}:{freq})"},
        "volume": {"fql_template": "P_VOLUME({start}:{end}:{freq})"},
    }
}


def test_generate_formula_basic():
    out = fg.generate_formula("BABA-CN", "price", DICT, start="-2Y", end="0D", freq="D")
    assert out == '=FDS("BABA-CN", "P_PRICE(-2Y:0D:D)")'


def test_generate_formula_unknown_metric():
    out = fg.generate_formula("X", "nope", DICT)
    assert out.startswith("# ERROR: Unknown metric")


def test_generate_formula_partial_placeholders():
    # only some placeholders provided -> others left intact
    out = fg.generate_formula("X", "price", DICT, start="-1Y")
    assert "-1Y" in out and "{end}" in out


def test_method_a_timeseries():
    a = fg.method_a_timeseries_formulas("BABA-CN", DICT, start="-2Y", end="0D", freq="D")
    assert a["close"] == '=FDS("BABA-CN", "P_PRICE(-2Y:0D:D)")'
    assert a["volume"] == '=FDS("BABA-CN", "P_VOLUME(-2Y:0D:D)")'
    assert "P_DATE" in a["date"]


def test_method_b_offset_grid():
    grid = fg.method_b_offset_grid(DICT, lookback=10, ticker_cell="$A$2", header_rows=3)
    assert len(grid) == 10
    first = grid[0]
    assert first["row"] == 4 and first["offset"] == 0
    # relative pattern matches the reference
    assert first["relative_formula"] == '=FDS($A$2,"P_PRICE(-"&(ROW()-3)&"D)")'
    # explicit pattern references column B for the row
    assert first["explicit_date_formula"] == '=FDS($A$2,"P_PRICE("&B4&")")'


def test_build_workbook_method_a_opens():
    data = fg.build_formula_workbook(["BABA-CN", "PDD-CN"], DICT, method="A", layout="per_ticker")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "Instructions" in wb.sheetnames
    assert "BABA-CN" in wb.sheetnames
    ws = wb["BABA-CN"]
    assert ws.cell(row=1, column=1).value == "date"
    assert ws.cell(row=2, column=2).value.startswith('=FDS("BABA-CN"')


def test_build_workbook_method_a_stacked():
    data = fg.build_formula_workbook(["AAA", "BBB"], DICT, method="A", layout="stacked")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "AllTickers" in wb.sheetnames
    ws = wb["AllTickers"]
    assert ws.cell(row=1, column=1).value == "ticker"
    assert ws.cell(row=2, column=1).value == "AAA"


def test_build_workbook_method_b_opens():
    data = fg.build_formula_workbook(["BABA-CN"], DICT, method="B", lookback=20)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb["BABA-CN"]
    assert ws.cell(row=2, column=1).value == "BABA-CN"  # A2 = ticker
    # relative formula present in column C
    assert "ROW()" in str(ws.cell(row=4, column=3).value)
