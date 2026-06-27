"""Phase D: weekly snapshot store delete/clear (frees uploaded-data blobs).

delete_snapshot removes one row by id; clear_all_snapshots wipes the table and
returns the count. Both are idempotent and never raise (missing id -> no-op).
Uses a temp DB like the other store tests.
"""
from app.weekly import snapshot_store as wsnap


def _save(n: int, db):
    ids = []
    for i in range(n):
        ids.append(wsnap.save_snapshot({"tickers": {f"T{i}-HK": []}},
                                       name=f"snap{i}", make_active=True, db_path=db))
    return ids


def test_delete_one_leaves_rest(temp_db):
    ids = _save(3, temp_db)
    assert len(wsnap.list_snapshots(db_path=temp_db)) == 3
    ok = wsnap.delete_snapshot(ids[0], db_path=temp_db)
    assert ok is True
    rows = wsnap.list_snapshots(db_path=temp_db)
    assert len(rows) == 2
    assert ids[0] not in [r["id"] for r in rows]


def test_delete_active_falls_back_to_newest(temp_db):
    ids = _save(3, temp_db)
    # newest (ids[2]) is active; delete it -> get_active falls back to next newest
    wsnap.delete_snapshot(ids[2], db_path=temp_db)
    active = wsnap.get_active(db_path=temp_db)
    assert active is not None
    assert active["id"] == ids[1]


def test_delete_nonexistent_id_no_raise(temp_db):
    _save(2, temp_db)
    # never raises; returns False for an unknown id
    assert wsnap.delete_snapshot(999999, db_path=temp_db) is False
    assert len(wsnap.list_snapshots(db_path=temp_db)) == 2


def test_clear_all_returns_count_then_zero(temp_db):
    _save(3, temp_db)
    n = wsnap.clear_all_snapshots(db_path=temp_db)
    assert n == 3
    assert wsnap.list_snapshots(db_path=temp_db) == []
    # idempotent: clearing again removes nothing and never raises
    assert wsnap.clear_all_snapshots(db_path=temp_db) == 0


def test_clear_all_on_empty_table(temp_db):
    # init runs implicitly; nothing to clear -> 0, no raise
    assert wsnap.clear_all_snapshots(db_path=temp_db) == 0
