"""CHANGE 1 — demo seeding removed: empty DB yields clean empty states.

The bundled demo loader and sample universe/prices were removed. A fresh DB must
expose no active dictionary/universe/snapshot and the screen must return an
empty (non-crashing) result.
"""
import pandas as pd

from app import settings_store as ss
from app.web import common


def test_empty_db_has_no_active_assets(temp_db):
    assert ss.get_active_dictionary(temp_db) is None
    assert ss.get_active_universe(temp_db) is None
    assert ss.get_active_snapshot(temp_db) is None
    assert ss.list_universes(temp_db) == []


def test_empty_db_screen_is_empty_not_crash(temp_db):
    res = common.run_active_screen(temp_db)
    assert res.get("_empty") is True
    assert isinstance(res["master"], pd.DataFrame)
    assert res["master"].empty


def test_no_demo_module():
    """app.demo must no longer exist."""
    import importlib

    try:
        importlib.import_module("app.demo")
    except ModuleNotFoundError:
        return
    raise AssertionError("app.demo should have been removed")
