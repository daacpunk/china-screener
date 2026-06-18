"""CHANGE 2 — uploading a user dictionary voids the bundled demo dictionary."""
import json

from app import demo as demo_mod
from app import settings_store as ss

USER_DICT = json.dumps({"formulas": {
    "user_metric": {"fql_template": "P_USER({start})"},
}})


def test_user_upload_voids_demo_dictionary(temp_db):
    # Seed the demo dictionary (tagged is_demo=True via demo loader).
    demo_mod.load_demo_data(temp_db)
    versions = ss.list_dictionaries(temp_db)
    assert len(versions) >= 1
    demo_active = ss.get_active_dictionary(temp_db)
    assert demo_active is not None

    # User uploads their own dictionary (is_demo defaults False), then void demo.
    ss.add_dictionary(USER_DICT, "# user wiki", filename="user.json",
                      note="real upload", make_active=True, is_demo=False, db_path=temp_db)
    removed = ss.void_demo_dictionaries(temp_db)
    assert removed >= 1

    # Demo rows gone; only the user's row remains and is active.
    versions = ss.list_dictionaries(temp_db)
    assert all(v["filename"] != "dictionary.json" for v in versions)
    active = ss.get_active_dictionary(temp_db)
    assert active["filename"] == "user.json"
    assert "user_metric" in active["data"]["formulas"]
    assert sum(v["is_active"] for v in versions) == 1


def test_void_never_touches_user_rows(temp_db):
    ss.add_dictionary(USER_DICT, filename="u1.json", is_demo=False, db_path=temp_db)
    ss.add_dictionary(USER_DICT, filename="u2.json", is_demo=False, db_path=temp_db)
    removed = ss.void_demo_dictionaries(temp_db)
    assert removed == 0
    assert len(ss.list_dictionaries(temp_db)) == 2
