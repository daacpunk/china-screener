"""Dictionary-version validation, persistence, encryption, screen params."""
import json

import pytest

from app import crypto
from app import settings_store as ss


VALID_DICT = json.dumps({"formulas": {"price": {"fql_template": "P_PRICE({start})"}}})
BAD_NO_FORMULAS = json.dumps({"foo": 1})
BAD_NO_TEMPLATE = json.dumps({"formulas": {"price": {"label": "x"}}})
BAD_JSON = "{not valid json"


def test_validate_dictionary_ok():
    data = ss.validate_dictionary(VALID_DICT)
    assert "formulas" in data


@pytest.mark.parametrize("bad", [BAD_NO_FORMULAS, BAD_NO_TEMPLATE, BAD_JSON])
def test_validate_dictionary_rejects(bad):
    with pytest.raises(ValueError):
        ss.validate_dictionary(bad)


def test_dictionary_versioning_and_diff(temp_db):
    r1 = ss.add_dictionary(VALID_DICT, "# wiki", filename="v1.json", db_path=temp_db)
    assert r1["diff"]["added"] == ["price"]
    active = ss.get_active_dictionary(temp_db)
    assert active["data"]["formulas"]["price"]["fql_template"] == "P_PRICE({start})"
    # add a second with an extra metric
    d2 = json.dumps({"formulas": {
        "price": {"fql_template": "P_PRICE({start})"},
        "volume": {"fql_template": "P_VOLUME({start})"},
    }})
    r2 = ss.add_dictionary(d2, filename="v2.json", db_path=temp_db)
    assert "volume" in r2["diff"]["added"]
    assert "price" in r2["diff"]["unchanged"]
    # only one active
    versions = ss.list_dictionaries(temp_db)
    assert sum(v["is_active"] for v in versions) == 1


def test_bad_dictionary_keeps_prior_active(temp_db):
    ss.add_dictionary(VALID_DICT, filename="good.json", db_path=temp_db)
    before = ss.get_active_dictionary(temp_db)
    with pytest.raises(ValueError):
        ss.add_dictionary(BAD_NO_TEMPLATE, filename="bad.json", db_path=temp_db)
    after = ss.get_active_dictionary(temp_db)
    assert before["id"] == after["id"]  # unchanged


def test_screen_params_persist_and_reset(temp_db):
    p = ss.get_screen_params(temp_db)
    p["rsi_oversold"] = 25.0
    ss.set_screen_params(p, temp_db)
    assert ss.get_screen_params(temp_db)["rsi_oversold"] == 25.0
    ss.reset_screen_params(temp_db)
    assert ss.get_screen_params(temp_db)["rsi_oversold"] == 30.0


def test_api_key_encryption_and_masking(temp_db):
    ss.set_api_key("anthropic", "sk-secret-abcd1234", model="claude-x", enabled=True, db_path=temp_db)
    # round-trips
    assert ss.get_api_key("anthropic", temp_db) == "sk-secret-abcd1234"
    cfg = ss.get_provider_config("anthropic", temp_db)
    assert cfg["has_key"] and cfg["enabled"]
    assert cfg["masked"].endswith("1234")
    assert "secret" not in cfg["masked"]


def test_env_var_takes_precedence(temp_db, monkeypatch):
    ss.set_api_key("deepseek", "stored-key", db_path=temp_db)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    assert ss.get_api_key("deepseek", temp_db) == "env-key"


def test_crypto_roundtrip(temp_db):
    tok = crypto.encrypt("hello")
    assert tok != "hello"
    assert crypto.decrypt(tok) == "hello"
    assert crypto.decrypt("garbage") == ""
