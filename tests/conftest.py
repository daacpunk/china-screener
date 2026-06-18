import os
import sys
import tempfile

import pytest

# Ensure project root importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture()
def temp_db(monkeypatch):
    """Isolated temp SQLite DB per test."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "test.db")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setenv("APP_SECRET", "unit-test-secret")
    from app.db import init_db
    init_db(path)
    return path
