"""Shared helpers for web routes: templates, active-universe assembly, screen run."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from fastapi.templating import Jinja2Templates

from .. import data_ingest as di
from .. import screen_engine as se
from .. import settings_store as ss

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

TABS = [
    {"id": "universe", "label": "Universe", "href": "/universe", "n": 1},
    {"id": "formula", "label": "Formula Generator", "href": "/formula", "n": 2},
    {"id": "data", "label": "Data & Indicators", "href": "/data", "n": 3},
    {"id": "results", "label": "Results", "href": "/results", "n": 4},
    {"id": "settings", "label": "Settings", "href": "/settings", "n": 5},
]


def base_ctx(request, active: str, **extra) -> Dict[str, Any]:
    ctx = {"request": request, "tabs": TABS, "active_tab": active}
    ctx.update(extra)
    return ctx


def assemble_active_universe(db_path: Optional[str] = None) -> pd.DataFrame:
    """Combine active uploaded universe + manual tickers into one frame.

    Applies/refreshes below_floor flag using current adv_floor param.
    """
    params = ss.get_screen_params(db_path)
    floor = float(params.get("adv_floor", 10_000_000))
    uni_row = ss.get_active_universe(db_path)
    frames = []
    if uni_row and uni_row.get("csv_text"):
        base = di.csv_to_df(uni_row["csv_text"])
        frames.append(base)
        if uni_row.get("manual_csv"):
            man = di.csv_to_df(uni_row["manual_csv"])
            if not man.empty:
                man["below_floor"] = False  # manual always included
                frames.append(man)
    if not frames:
        return pd.DataFrame(columns=["ticker", "name", "sector", "sub_industry", "index_weight", "adv_usd_20d", "below_floor"])
    df = pd.concat(frames, ignore_index=True)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "adv_usd_20d" in df.columns and "below_floor" not in df.columns:
        df["below_floor"] = pd.to_numeric(df["adv_usd_20d"], errors="coerce").fillna(0) < floor
    if "below_floor" not in df.columns:
        df["below_floor"] = False
    # dedupe by ticker keeping first
    df = df.drop_duplicates(subset=["ticker"], keep="first").reset_index(drop=True)
    return df


def active_prices(db_path: Optional[str] = None) -> pd.DataFrame:
    snap = ss.get_active_snapshot(db_path)
    if not snap or not snap.get("csv_text"):
        return pd.DataFrame(columns=["ticker", "date", "close", "volume"])
    return di.csv_to_df(snap["csv_text"])


def run_active_screen(db_path: Optional[str] = None) -> Dict[str, pd.DataFrame]:
    prices = active_prices(db_path)
    uni = assemble_active_universe(db_path)
    params = ss.get_screen_params(db_path)
    if prices.empty or uni.empty:
        empty = pd.DataFrame()
        return {"master": empty, "oversold": empty, "overbought": empty,
                "skipped": pd.DataFrame(), "_empty": True}
    res = se.run_screen(prices, uni, params)
    res["_empty"] = False
    return res


def df_to_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return df.where(pd.notna(df), None).to_dict("records")
