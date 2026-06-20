"""CHANGE 2 — the most recently uploaded universe is the active default and
persists across DB re-open (simulating a restart/redeploy)."""
from app import settings_store as ss
from app.db import init_db


def _csv(tag: str) -> str:
    return f"ticker,name,sector\n{tag},{tag} Co,Tech\n"


def test_newest_upload_becomes_active(temp_db):
    v1 = ss.add_universe(_csv("AAA"), filename="u1.csv", db_path=temp_db)
    assert ss.get_active_universe(temp_db)["id"] == v1

    v2 = ss.add_universe(_csv("BBB"), filename="u2.csv", db_path=temp_db)
    assert ss.get_active_universe(temp_db)["id"] == v2  # newest auto-advances


def test_active_persists_across_reopen(temp_db):
    ss.add_universe(_csv("AAA"), filename="u1.csv", db_path=temp_db)
    v2 = ss.add_universe(_csv("BBB"), filename="u2.csv", db_path=temp_db)

    # Simulate a restart: re-init the schema and reload from the same file.
    init_db(temp_db)
    ss.ensure_active_universe(temp_db)
    assert ss.get_active_universe(temp_db)["id"] == v2


def test_explicit_pin_is_respected(temp_db):
    v1 = ss.add_universe(_csv("AAA"), filename="u1.csv", db_path=temp_db)
    ss.add_universe(_csv("BBB"), filename="u2.csv", db_path=temp_db)
    ss.set_active_universe(v1, db_path=temp_db)  # user pins the older version
    assert ss.get_active_universe(temp_db)["id"] == v1
    # ensure_active_universe must not override an explicit pin
    ss.ensure_active_universe(temp_db)
    assert ss.get_active_universe(temp_db)["id"] == v1


def test_ensure_promotes_newest_when_none_active(temp_db):
    # Insert two versions but clear active flags (legacy/migrated DB scenario).
    ss.add_universe(_csv("AAA"), filename="u1.csv", db_path=temp_db)
    v2 = ss.add_universe(_csv("BBB"), filename="u2.csv", db_path=temp_db)
    from app.db import get_conn
    conn = get_conn(temp_db)
    conn.execute("UPDATE universes SET is_active=0")
    conn.commit()
    conn.close()

    promoted = ss.ensure_active_universe(temp_db)
    assert promoted == v2
    assert ss.get_active_universe(temp_db)["id"] == v2
