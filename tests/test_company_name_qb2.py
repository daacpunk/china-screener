"""Q-B2: company name in Analysis/Research notes + main Formula Generator.

Covers:
  (a) formula-generator output contains =FDS(...,"FG_COMPANY_NAME") per ticker
      when the company-name column is enabled (default), across every layout;
      and is omitted (backward-compatible) when disabled.
  (b) _row_line / _name_ticker_label render "Company Name (TICKER)" when a name
      is present and a bare "TICKER" when absent.
  (c) research_notes catalyst prompt shows "Company Name (TICKER)".
  (d) screen data path: a data dump carrying company names attaches `name` to
      the tidy price frame and reaches master rows even when the universe lacked
      a name (universe name preferred; never overwritten with blank).
"""
import io
import zipfile

import numpy as np
import pandas as pd

from app import data_ingest as di
from app import formula_gen as fg
from app import screen_engine as se
from app.llm.prompts import _name_ticker_label, _row_line
from app.llm.research_notes import build_catalyst_prompt


DICT = {
    "formulas": {
        "price": {"fql_template": "P_PRICE({start},{end},{freq})"},
        "volume": {"fql_template": "P_VOLUME_DAY({start},{end},{freq})"},
        "company_name": {"fql_template": "FG_COMPANY_NAME"},
    }
}


def _xl_blob(xlsx_bytes: bytes) -> bytes:
    z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    return b"".join(z.read(n) for n in z.namelist() if n.startswith("xl/"))


# ---------------------------------------------------------------------------
# (a) formula generator pulls FG_COMPANY_NAME
# ---------------------------------------------------------------------------
def test_company_name_formula_literal_and_cell():
    assert fg.company_name_formula("9988-HK", DICT) == '=FDS("9988-HK","FG_COMPANY_NAME")'
    assert fg.company_name_formula("A2", DICT) == '=FDS(A2,"FG_COMPANY_NAME")'
    assert fg.company_name_formula("$A$2", DICT) == '=FDS($A$2,"FG_COMPANY_NAME")'


def test_generator_includes_fg_company_name_all_layouts():
    for layout in ("spill", "per_ticker", "stacked"):
        b = fg.build_formula_workbook(["9988-HK", "700-HK"], DICT, method="A",
                                      lookback=5, layout=layout)
        blob = _xl_blob(b)
        assert b"FG_COMPANY_NAME" in blob, layout
        assert b"company_name" in blob, layout


def test_generator_method_b_includes_fg_company_name():
    b = fg.build_formula_workbook(["9988-HK"], DICT, method="B", lookback=5)
    assert b"FG_COMPANY_NAME" in _xl_blob(b)


def test_generator_backward_compatible_when_disabled():
    b = fg.build_formula_workbook(["9988-HK"], DICT, method="A", lookback=5,
                                  layout="spill", include_name=False)
    assert b"FG_COMPANY_NAME" not in _xl_blob(b)


def test_generator_falls_back_to_default_field_when_dict_lacks_entry():
    # dictionary without a company_name entry -> still emits FG_COMPANY_NAME.
    d = {"formulas": {"price": {"fql_template": "P_PRICE({start},{end},{freq})"},
                      "volume": {"fql_template": "P_VOLUME_DAY({start},{end},{freq})"}}}
    b = fg.build_formula_workbook(["9988-HK"], d, method="A", lookback=5, layout="spill")
    assert b"FG_COMPANY_NAME" in _xl_blob(b)


# ---------------------------------------------------------------------------
# (b) _row_line / label ordering: "Company Name (TICKER)"
# ---------------------------------------------------------------------------
def test_name_ticker_label_with_name():
    assert _name_ticker_label({"ticker": "9988-HK", "name": "Alibaba Group"}) == "Alibaba Group (9988-HK)"


def test_name_ticker_label_bare_ticker_when_name_absent():
    assert _name_ticker_label({"ticker": "700-HK"}) == "700-HK"
    assert _name_ticker_label({"ticker": "700-HK", "name": None}) == "700-HK"
    assert _name_ticker_label({"ticker": "700-HK", "name": ""}) == "700-HK"
    # name equal to ticker collapses to bare ticker (no redundant parens)
    assert _name_ticker_label({"ticker": "X", "name": "X"}) == "X"


def test_row_line_renders_name_then_ticker():
    line = _row_line({"ticker": "9988-HK", "name": "Alibaba Group",
                      "sector": "Cons Disc", "sub_industry": "Retail"})
    assert line.startswith("- Alibaba Group (9988-HK) |")
    # old order must NOT appear
    assert "9988-HK (Alibaba Group)" not in line


def test_row_line_bare_ticker_when_name_missing():
    line = _row_line({"ticker": "700-HK", "sector": "Tech", "sub_industry": "Semis"})
    assert line.startswith("- 700-HK |")


# ---------------------------------------------------------------------------
# (c) research_notes catalyst prompt shows "Company Name (TICKER)"
# ---------------------------------------------------------------------------
def test_catalyst_prompt_shows_name_ticker():
    row = {"ticker": "9988-HK", "name": "Alibaba Group", "sector": "Cons Disc",
           "sub_industry": "Retail"}
    prompt = build_catalyst_prompt(row, "long", with_news=True)
    assert "Alibaba Group (9988-HK)" in prompt
    # row line inside the prompt also uses the new order
    assert "9988-HK (Alibaba Group)" not in prompt


def test_catalyst_prompt_bare_ticker_when_name_missing():
    row = {"ticker": "700-HK", "sector": "Tech", "sub_industry": "Semis"}
    prompt = build_catalyst_prompt(row, "short", with_news=False)
    assert "700-HK" in prompt


# ---------------------------------------------------------------------------
# (d) screen data path: data-dump company name reaches master rows
# ---------------------------------------------------------------------------
def _dump_csv(tickers, name_map):
    lines = ["ticker,date,close,volume,company_name"]
    for t in tickers:
        for i in range(120):
            d = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).date()
            lines.append(f"{t},{d},{100 + i % 5},1000000,{name_map[t]}")
    return "\n".join(lines).encode()


def test_parse_prices_attaches_company_name_from_dump():
    tidy, _ = di.parse_prices(_dump_csv(["AAA"], {"AAA": "Alpha Corp"}), "dump.csv")
    assert "name" in tidy.columns
    assert tidy["name"].dropna().iloc[0] == "Alpha Corp"


def _prices_with_names(tickers, name_map):
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2024-01-01", periods=120)
    rows = []
    for t in tickers:
        prices = 100 * np.cumprod(1 + rng.normal(0.0002, 0.012, 120))
        for d, p in zip(dates, prices):
            rows.append({"ticker": t, "date": d, "close": float(p),
                         "volume": 1_000_000, "name": name_map.get(t)})
    return pd.DataFrame(rows)


def test_data_dump_name_reaches_master_when_universe_lacks_name():
    tickers = ["AAA", "BBB", "CCC"]
    names = {t: f"{t} Holdings" for t in tickers}
    prices = _prices_with_names(tickers, names)
    # universe with NO name column at all
    uni = pd.DataFrame([{"ticker": t, "sector": "X", "sub_industry": "Banks",
                         "index_weight": 1.0, "adv_usd_20d": 50_000_000,
                         "below_floor": False} for t in tickers])
    res = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, min_bars=60))
    m = res["master"].set_index("ticker")
    for t in tickers:
        assert m.loc[t, "name"] == names[t]


def test_universe_name_preferred_over_dump_name():
    prices = _prices_with_names(["AAA"], {"AAA": "DUMP NAME"})
    uni = pd.DataFrame([{"ticker": "AAA", "name": "UNIVERSE NAME", "sector": "X",
                         "sub_industry": "Banks", "index_weight": 1.0,
                         "adv_usd_20d": 50_000_000, "below_floor": False}])
    res = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, min_bars=60))
    assert res["master"].set_index("ticker").loc["AAA", "name"] == "UNIVERSE NAME"


def test_blank_dump_name_does_not_overwrite_universe_name():
    prices = _prices_with_names(["AAA"], {"AAA": None})  # no dump name
    uni = pd.DataFrame([{"ticker": "AAA", "name": "UNIVERSE NAME", "sector": "X",
                         "sub_industry": "Banks", "index_weight": 1.0,
                         "adv_usd_20d": 50_000_000, "below_floor": False}])
    res = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, min_bars=60))
    assert res["master"].set_index("ticker").loc["AAA", "name"] == "UNIVERSE NAME"


def test_multisheet_spill_dump_carries_company_name():
    # A multi-sheet workbook (one per-ticker sheet, each with a company_name
    # column carrying the RESOLVED FactSet name) must surface a `name` column
    # keyed to the right ticker.
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    names = {"AAA-CN": "Alpha Retail", "BBB-CN": "Beta Energy"}
    for t, nm in names.items():
        ws = wb.create_sheet(t)
        ws.append(["ticker", "date", "close", "volume", "company_name"])
        for i in range(80):
            d = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).date()
            ws.append([t, str(d), 100 + i % 5, 1_000_000, nm if i == 0 else None])
    bio = io.BytesIO()
    wb.save(bio)
    tidy, report = di.parse_prices(bio.getvalue(), "spill.xlsx")
    assert report.get("multisheet_spill") is True
    assert "name" in tidy.columns
    got = {t: g["name"].dropna().iloc[0] for t, g in tidy.groupby("ticker")}
    assert got == names
