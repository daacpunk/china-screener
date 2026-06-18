"""Universe parsing robustness: header detection, alias widening, 0-row
reporting, and manual column-mapping overrides."""
import io

import pandas as pd

from app import data_ingest as di


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def test_basic_ticker_alias_symbol():
    csv = "Symbol,Name,Sector\n0700-HK,Tencent,Comm\n9988-HK,Alibaba,Cons\n"
    df, rep = di.parse_universe(_csv_bytes(csv), "u.csv")
    assert rep["rows"] == 2
    assert set(df["ticker"]) == {"0700-HK", "9988-HK"}
    assert rep["mapping"]["ticker"] == "symbol"


def test_wider_alias_stock_code():
    csv = "Stock Code,Company\n600519-CN,Moutai\n"
    df, rep = di.parse_universe(_csv_bytes(csv), "u.csv")
    assert rep["rows"] == 1
    assert df.iloc[0]["ticker"] == "600519-CN"


def test_header_detection_with_title_rows():
    # Two metadata rows above the real header (typical FactSet/MSCI export).
    csv = (
        "MSCI China Index Constituents,,\n"
        "As of 2026-05-31,,\n"
        "Ticker,Name,Sector\n"
        "0700-HK,Tencent,Comm\n"
        "9988-HK,Alibaba,Cons\n"
    )
    df, rep = di.parse_universe(_csv_bytes(csv), "u.csv")
    assert rep["rows"] == 2
    assert rep["mapping"]["ticker"] == "ticker"


def test_zero_rows_when_no_ticker_column():
    csv = "Foo,Bar\n1,2\n3,4\n"
    df, rep = di.parse_universe(_csv_bytes(csv), "u.csv")
    assert rep["rows"] == 0
    assert rep["mapping"]["ticker"] is None
    assert "foo" in rep["columns_seen"] and "bar" in rep["columns_seen"]


def test_manual_override_maps_unknown_column():
    # Identifier column has an unrecognized name; override forces it.
    csv = "MyId,Name\nAAA-CN,Alpha\nBBB-CN,Beta\n"
    df0, rep0 = di.parse_universe(_csv_bytes(csv), "u.csv")
    # 'myid' fuzzy-contains 'id' so it may auto-map; force a clean case:
    csv2 = "WeirdHeader,Name\nAAA-CN,Alpha\nBBB-CN,Beta\n"
    df_auto, rep_auto = di.parse_universe(_csv_bytes(csv2), "u.csv")
    assert rep_auto["rows"] == 0  # not auto-detected
    df_ovr, rep_ovr = di.parse_universe(
        _csv_bytes(csv2), "u.csv", overrides={"ticker": "WeirdHeader"}
    )
    assert rep_ovr["rows"] == 2
    assert set(df_ovr["ticker"]) == {"AAA-CN", "BBB-CN"}


def test_ragged_title_rows_with_extra_data_columns():
    # Title rows have FEWER columns than the real data rows (classic FactSet/
    # MSCI export). The C engine would raise a tokenizing error; we must still
    # find the header and import all data rows.
    csv = (
        "MSCI China Index,,\n"
        "As of 2026-05-31,,\n"
        "Symbol,Name,GICS Sector,Index Weight,20D ADV USD\n"
        "0700-HK,Tencent,Communication Services,12.3,800000000\n"
        "9988-HK,Alibaba,Consumer Discretionary,8.5,650000000\n"
        "1810-HK,Xiaomi,Information Technology,3.2,300000000\n"
    )
    df, rep = di.parse_universe(_csv_bytes(csv), "uni.csv")
    assert rep["rows"] == 3
    assert rep["mapping"]["ticker"] == "symbol"
    assert rep["mapping"]["adv_usd_20d"] == "20d adv usd"
    assert set(df["ticker"]) == {"0700-HK", "9988-HK", "1810-HK"}


def test_msci_index_export_hierarchy():
    # Mirrors a real MSCI index export: title rows, a Name/Symbol header, an
    # index summary row (CN-MSX), and interleaved GICS group rows (2-digit =
    # sector, 6-digit = sub-industry) whose constituents follow them.
    csv = (
        "MSCI China (MS302400),,,\n"
        "Y65.57,,,\n"
        ",,,\n"
        "Name,Symbol,% Index Weight,Price\n"
        "MSCI China,CN-MSX,100.00,75.16\n"
        "10 Energy,,3.39,-\n"
        "101010 Energy Equipment & Services,,0.12,-\n"
        "Yantai Jereh Class A,BD5CMC,0.06,22.9\n"
        "101020 Oil Gas & Consumable Fuels,,3.26,-\n"
        "China Oilfield Services H,2883-HK,0.07,0.96\n"
        "25 Consumer Discretionary,,23.73,-\n"
        "255030 Broadline Retail,,12.55,-\n"
        "Alibaba Group H,9988-HK,8.50,80.1\n"
        "PDD Holdings ADR,PDD,4.20,120.0\n"
    )
    df, rep = di.parse_universe(_csv_bytes(csv), "MSCI-China.csv")
    # 4 real constituents; index + group rows dropped
    assert rep["rows"] == 4
    assert "CN-MSX" not in set(df["ticker"])
    assert set(df["ticker"]) == {"BD5CMC", "2883-HK", "9988-HK", "PDD"}
    # sector / sub-industry derived from the GICS group rows
    row = df.set_index("ticker").loc["9988-HK"]
    assert row["sector"] == "Consumer Discretionary"
    assert row["sub_industry"] == "Broadline Retail"
    assert df.set_index("ticker").loc["BD5CMC"]["sector"] == "Energy"
    assert df["sector"].notna().all() and df["sub_industry"].notna().all()


def test_clean_file_not_broken_by_header_detection():
    csv = "ticker,name,sector,index_weight,adv_usd_20d\nX-CN,Xco,Tech,1.5,50000000\n"
    df, rep = di.parse_universe(_csv_bytes(csv), "u.csv")
    assert rep["rows"] == 1
    assert float(df.iloc[0]["index_weight"]) == 1.5
    assert float(df.iloc[0]["adv_usd_20d"]) == 50000000
