"""IMPROVEMENT 2: ex-dividend FactSet event-date pull.

The non-refreshing LIVE earnings pulls (RTP_EARNINGS_RELEASE_DATE /
RTP_EARNINGS_RELEASE_STATUS via =FDSLIVE) were REMOVED because the live RTP
fields do not refresh in Excel (they return nothing). Ex-dividend
(FCA_EVENT_DATE via =FDS) is now the SOLE event-date source.

Covers the surviving layers:
  1. formula_gen  -> emits the ex-dividend =FDS formula (with doubled-quote
     escaping) when events are enabled; omits it when disabled; and NEVER emits
     any =FDSLIVE / RTP_EARNINGS formula.
  2. data_ingest  -> decodes a YYYYMMDD ex-div int (e.g. 20260526) to a real
     Timestamp; leaves things alone when the column is absent
     (backward-compatible).
  3. screen_engine -> sets event_flag True + populates event_date when a pulled
     ex-div date falls inside the event window; False when absent/outside.
  4. dictionary    -> ships an ``ex_dividend_date`` entry whose template stores
     the FCA_EVENT_DATE args with single double-quotes (doubling at emit time)
     and NO RTP earnings entries remain.
"""
import io
import json
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

from app import data_ingest as di
from app import formula_gen as fg
from app import screen_engine as se

ROOT = Path(__file__).resolve().parent.parent
DICT = json.loads((ROOT / "sample_data" / "dictionary.json").read_text())

# Verified exact emitted strings (doubled double-quotes round-trip in Excel).
# Ex-dividend keeps the =FDS FCA_EVENT_DATE pull UNCHANGED.
EX_DIV_LITERAL = '=FDS("9988-HK","FCA_EVENT_DATE(0,""CASH_DIST"",""EXDATE"",""YYYYMMDD"")")'
EX_DIV_CELLREF = '=FDS(A2,"FCA_EVENT_DATE(0,""CASH_DIST"",""EXDATE"",""YYYYMMDD"")")'


# --- Layer 1: formula generator ------------------------------------------

def test_single_cell_ex_dividend_formula_exact_escaping():
    # Ex-dividend =FDS pull is UNCHANGED (doubled-quote escaping).
    assert fg.ex_dividend_formula("9988-HK", DICT) == EX_DIV_LITERAL
    assert fg.ex_dividend_formula("A2", DICT) == EX_DIV_CELLREF


def test_earnings_helpers_removed():
    # The removed live-earnings helpers must no longer exist on the module.
    for name in ("fdslive_formula", "earnings_date_formula",
                 "earnings_status_formula", "_earnings_template",
                 "_earnings_status_template", "_event_fql"):
        assert not hasattr(fg, name), name


def _headers(data, sheet=None):
    wb = openpyxl.load_workbook(io.BytesIO(data))
    if sheet is None:
        sheet = [s for s in wb.sheetnames if s != "Instructions"][0]
    ws = wb[sheet]
    return [c.value for c in ws[1]], ws, wb


def _all_formula_text(data):
    wb = openpyxl.load_workbook(io.BytesIO(data))
    out = []
    for sn in wb.sheetnames:
        for row in wb[sn].iter_rows():
            for c in row:
                if c.value is not None:
                    out.append(str(c.value))
    return "\n".join(out)


def test_workbook_emits_ex_div_and_no_fdslive_when_enabled():
    for layout in ("spill", "stacked", "per_ticker"):
        data = fg.build_formula_workbook(["9988-HK"], DICT, method="A",
                                         layout=layout, lookback=20,
                                         include_events=True)
        hdrs, _ws, _wb = _headers(data)
        assert "ex_dividend_date" in hdrs, layout
        # earnings columns must be gone from the header
        assert "earnings_date" not in hdrs, layout
        assert "earnings_status" not in hdrs, layout
        text = _all_formula_text(data)
        # doubled-quote ex-div =FDS template present (UNCHANGED) ...
        assert 'FCA_EVENT_DATE(0,""CASH_DIST"",""EXDATE"",""YYYYMMDD"")' in text, layout
        # ... and NO live earnings pulls anywhere.
        assert "FDSLIVE" not in text, layout
        assert "RTP_EARNINGS" not in text, layout
        assert "FE_REP_DT_NEXT" not in text, layout


def test_method_b_emits_ex_div_and_no_fdslive_when_enabled():
    data = fg.build_formula_workbook(["9988-HK"], DICT, method="B", lookback=20,
                                     include_events=True)
    text = _all_formula_text(data)
    assert 'FCA_EVENT_DATE(0,""CASH_DIST"",""EXDATE"",""YYYYMMDD"")' in text
    assert "FDSLIVE" not in text
    assert "RTP_EARNINGS" not in text
    assert "FE_REP_DT_NEXT" not in text


def test_workbook_omits_event_formulas_when_disabled():
    for layout in ("spill", "stacked", "per_ticker"):
        data = fg.build_formula_workbook(["9988-HK"], DICT, method="A",
                                         layout=layout, lookback=20,
                                         include_events=False)
        hdrs, _ws, _wb = _headers(data)
        assert "earnings_date" not in hdrs, layout
        assert "earnings_status" not in hdrs, layout
        assert "ex_dividend_date" not in hdrs, layout
        text = _all_formula_text(data)
        assert "FCA_EVENT_DATE" not in text, layout
        assert "FDSLIVE" not in text, layout
        assert "RTP_EARNINGS" not in text, layout


def test_include_event_legacy_flag_is_noop():
    # The legacy singular ``include_event`` toggle must not crash and must not
    # emit any earnings / RTP formula.
    data = fg.build_formula_workbook(["9988-HK"], DICT, method="A",
                                     layout="spill", lookback=20,
                                     include_event=True, include_events=True)
    text = _all_formula_text(data)
    assert "FDSLIVE" not in text
    assert "RTP_EARNINGS" not in text
    # ex-dividend still present
    assert 'FCA_EVENT_DATE(0,""CASH_DIST"",""EXDATE"",""YYYYMMDD"")' in text


def test_spill_price_vol_columns_untouched_by_events():
    # Event columns append AFTER the close/volume block so the spill-activation
    # macro's B/C/D (date/close/volume) references are preserved.
    data = fg.build_formula_workbook(["9988-HK"], DICT, method="A",
                                     layout="spill", lookback=109,
                                     include_events=True)
    _hdrs, ws, _wb = _headers(data, sheet="9988-HK")
    def _af(v):
        return str(v).replace("_xlfn._xlws.", "").replace("_xlfn.", "")
    assert _af(ws.cell(row=2, column=3).value) == '=FDS(A2,"P_PRICE(0,-109D,D)")'
    assert _af(ws.cell(row=2, column=4).value) == '=FDS(A2,"P_VOLUME_DAY(0,-109D,D)")'


# --- Layer 2: data_ingest decode -----------------------------------------

def test_decode_event_date_yyyymmdd_int():
    assert di._decode_event_date(20260526) == pd.Timestamp("2026-05-26")
    assert di._decode_event_date("20260526") == pd.Timestamp("2026-05-26")
    assert di._decode_event_date(20260526.0) == pd.Timestamp("2026-05-26")


def test_decode_event_date_datestring_and_serial():
    assert di._decode_event_date("2026-05-26") == pd.Timestamp("2026-05-26")
    # Excel/FactSet-Julian serial (1899-12-30 origin) for 2026-05-26
    serial = (pd.Timestamp("2026-05-26") - pd.Timestamp("1899-12-30")).days
    assert 20000 <= serial <= 80000
    assert di._decode_event_date(serial) == pd.Timestamp("2026-05-26")


def test_decode_event_date_blank_and_errors_none():
    for v in (None, "", "  ", "nan", "#N/A", "#ERR", "@NA", float("nan")):
        assert di._decode_event_date(v) is None


# --- Layer 3: screen_engine event flagging --------------------------------

def _uni_prices():
    rng = np.random.default_rng(3)
    dates = pd.bdate_range("2024-01-01", periods=120)
    rows, uni = [], []
    for t, sub, shock in (("AAA", "Banks", -0.20), ("BBB", "Banks", 0.0),
                          ("CCC", "Banks", 0.0), ("DDD", "Tech", 0.25),
                          ("EEE", "Tech", 0.0)):
        rets = rng.normal(0.0002, 0.012, 120)
        if shock:
            rets[-7:] += (1 + shock) ** (1 / 7) - 1
        px = 100.0 * np.cumprod(1 + rets)
        for d, p in zip(dates, px):
            rows.append({"ticker": t, "date": d, "close": float(p),
                         "volume": 1_000_000})
        uni.append({"ticker": t, "name": t, "sector": "X", "sub_industry": sub,
                    "index_weight": 1.0, "adv_usd_20d": 50_000_000,
                    "below_floor": False})
    return pd.DataFrame(uni), pd.DataFrame(rows), dates.max()


def test_select_event_date_in_and_out_of_window():
    asof = pd.Timestamp("2026-06-14")
    # ex-div 3 days AGO -> in window (ex-div is ±window)
    ed, inw = se._select_event_date("20260611", asof, 7)
    assert ed == pd.Timestamp("2026-06-11") and inw is True
    # ex-div 3 days AHEAD -> in window
    ed, inw = se._select_event_date("20260617", asof, 7)
    assert ed == pd.Timestamp("2026-06-17") and inw is True
    # ex-div 60 days ahead -> nearest date surfaced but flag False
    ed, inw = se._select_event_date("20260813", asof, 7)
    assert ed == pd.Timestamp("2026-08-13") and inw is False
    # nothing parseable -> (None, False)
    assert se._select_event_date(None, asof, 7) == (None, False)


def test_run_screen_event_flag_from_pulled_exdiv_in_window():
    uni, prices, asof = _uni_prices()
    prices = prices.copy()
    # attach an in-window ex-div (2 days after asof) to AAA only
    exdiv = int((pd.Timestamp(asof) + pd.Timedelta(days=2)).strftime("%Y%m%d"))
    prices["ex_dividend_date"] = np.nan
    prices.loc[prices["ticker"] == "AAA", "ex_dividend_date"] = exdiv
    res = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, min_bars=60))
    m = res["master"].set_index("ticker")
    assert bool(m.loc["AAA", "event_flag"]) is True
    assert pd.to_datetime(m.loc["AAA", "event_date"]) == \
        pd.Timestamp(asof) + pd.Timedelta(days=2)
    # a ticker with no event date stays unflagged
    assert bool(m.loc["BBB", "event_flag"]) is False
    assert res["meta"]["event_data_loaded"] is True


def test_run_screen_no_event_columns_backward_compatible():
    uni, prices, _asof = _uni_prices()
    res = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, min_bars=60))
    m = res["master"].set_index("ticker")
    assert bool(m.loc["AAA", "event_flag"]) is False
    assert res["meta"]["event_data_loaded"] is False


def test_run_screen_exdiv_outside_window_not_flagged():
    uni, prices, asof = _uni_prices()
    prices = prices.copy()
    far = int((pd.Timestamp(asof) + pd.Timedelta(days=60)).strftime("%Y%m%d"))
    prices["ex_dividend_date"] = np.nan
    prices.loc[prices["ticker"] == "AAA", "ex_dividend_date"] = far
    res = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, min_bars=60))
    m = res["master"].set_index("ticker")
    # nearest date surfaced, but far outside the 7-day window -> flag False
    assert bool(m.loc["AAA", "event_flag"]) is False
    assert pd.to_datetime(m.loc["AAA", "event_date"]) == \
        pd.Timestamp(asof) + pd.Timedelta(days=60)


def test_run_screen_legacy_earnings_column_ignored():
    # Old dumps that still carry an earnings_date column must NOT error and must
    # NOT drive event flagging (ex-dividend is the sole source now).
    uni, prices, asof = _uni_prices()
    prices = prices.copy()
    near = int((pd.Timestamp(asof) + pd.Timedelta(days=2)).strftime("%Y%m%d"))
    prices["earnings_date"] = np.nan
    prices.loc[prices["ticker"] == "AAA", "earnings_date"] = near
    res = se.run_screen(prices, uni, dict(se.DEFAULT_PARAMS, min_bars=60))
    m = res["master"].set_index("ticker")
    # legacy earnings column ignored -> no event flagged from it
    assert bool(m.loc["AAA", "event_flag"]) is False
    assert res["meta"]["event_data_loaded"] is False


# --- Layer 4: dictionary --------------------------------------------------

def test_dictionary_has_ex_dividend_entry_with_single_quote_template():
    f = DICT["formulas"]
    assert "ex_dividend_date" in f
    tmpl = f["ex_dividend_date"]["fql_template"]
    # stored with SINGLE double-quotes (doubling happens at emit time)
    assert tmpl == 'FCA_EVENT_DATE(0,"CASH_DIST","EXDATE","YYYYMMDD")'
    assert '""' not in tmpl
    assert f["ex_dividend_date"]["family"] == "corporate_actions"


def test_dictionary_has_no_rtp_earnings_entries():
    f = DICT["formulas"]
    assert "earnings_release_status" not in f
    assert "next_earnings" not in f
    # No entry may resolve to an RTP earnings field.
    for entry in f.values():
        tmpl = (entry or {}).get("fql_template", "") if isinstance(entry, dict) else ""
        assert "RTP_EARNINGS" not in str(tmpl)
