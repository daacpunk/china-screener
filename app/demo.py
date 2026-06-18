"""Demo-mode seeding: load sample dictionary + universe + price snapshot into
the DB so the user can click Run Screen immediately with no FactSet/API keys.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from . import data_ingest as di
from . import settings_store as ss

_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def sample_paths():
    return {
        "dictionary_json": _SAMPLE_DIR / "dictionary.json",
        "dictionary_md": _SAMPLE_DIR / "dictionary.md",
        "universe_csv": _SAMPLE_DIR / "universe_sample.csv",
        "prices_csv": _SAMPLE_DIR / "prices_sample.csv",
    }


def load_demo_data(db_path: str | None = None) -> dict:
    """Seed demo dictionary, universe (with liquidity floor applied), and price
    snapshot. Returns a summary dict. Idempotent-ish (creates new versions)."""
    p = sample_paths()

    # dictionary
    json_text = p["dictionary_json"].read_text()
    md_text = p["dictionary_md"].read_text() if p["dictionary_md"].exists() else ""
    ss.add_dictionary(json_text, md_text, filename="dictionary.json",
                      note="demo seed", make_active=True, db_path=db_path)

    # universe — parse and apply default liquidity floor
    uni_bytes = p["universe_csv"].read_bytes()
    uni_df, _ = di.parse_universe(uni_bytes, "universe_sample.csv")
    params = ss.get_screen_params(db_path)
    floor = float(params.get("adv_floor", 10_000_000))
    uni_df["below_floor"] = uni_df["adv_usd_20d"].fillna(0) < floor
    ss.add_universe(uni_df.to_csv(index=False), manual_csv="",
                    filename="universe_sample.csv", note="demo seed",
                    make_active=True, db_path=db_path)

    # prices snapshot
    px_bytes = p["prices_csv"].read_bytes()
    tidy, report = di.parse_prices(px_bytes, "prices_sample.csv")
    import json
    ss.add_snapshot(tidy.to_csv(index=False), quality_json=json.dumps(report),
                    filename="prices_sample.csv", note="demo seed",
                    make_active=True, db_path=db_path)

    return {
        "tickers": int(tidy["ticker"].nunique()),
        "rows": int(len(tidy)),
        "universe_names": int(len(uni_df)),
        "below_floor": int(uni_df["below_floor"].sum()),
    }


def maybe_seed_on_startup(db_path: str | None = None) -> None:
    """Seed demo data on first run if DB is empty (no active dictionary)."""
    if ss.get_active_dictionary(db_path) is None:
        try:
            load_demo_data(db_path)
        except Exception:
            pass
