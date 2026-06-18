"""CHANGE 1 — model lists + default-model wiring into settings_store."""
from app.llm.models import DEFAULT_MODEL, PROVIDER_MODELS
from app import settings_store as ss


def test_provider_models_cover_three_providers():
    assert set(PROVIDER_MODELS.keys()) == {"perplexity", "anthropic", "deepseek"}
    for prov, models in PROVIDER_MODELS.items():
        assert models, f"{prov} has no models"
        for mid, label in models:
            assert isinstance(mid, str) and mid
            assert isinstance(label, str) and label


def test_default_model_is_first_entry():
    assert DEFAULT_MODEL["perplexity"] == "sonar"
    assert DEFAULT_MODEL["anthropic"] == "claude-opus-4-8"
    assert DEFAULT_MODEL["deepseek"] == "deepseek-v4-pro"


def test_expected_june_2026_models_present():
    pplx = dict(PROVIDER_MODELS["perplexity"])
    assert {"sonar", "sonar-pro", "sonar-reasoning", "sonar-reasoning-pro",
            "sonar-deep-research", "r1-1776"} <= set(pplx)
    anth = dict(PROVIDER_MODELS["anthropic"])
    assert {"claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5",
            "claude-fable-5", "claude-opus-4-7", "claude-opus-4-6"} <= set(anth)
    ds = dict(PROVIDER_MODELS["deepseek"])
    assert {"deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat",
            "deepseek-reasoner"} <= set(ds)


def test_settings_store_uses_new_defaults(temp_db):
    # No model passed -> falls back to the new DEFAULT_MODEL from llm.models.
    ss.set_api_key("anthropic", "sk-x", enabled=True, db_path=temp_db)
    cfg = ss.get_provider_config("anthropic", temp_db)
    assert cfg["model"] == "claude-opus-4-8"
    ss.set_api_key("deepseek", "sk-y", enabled=True, db_path=temp_db)
    assert ss.get_provider_config("deepseek", temp_db)["model"] == "deepseek-v4-pro"
    ss.set_api_key("perplexity", "sk-z", enabled=True, db_path=temp_db)
    assert ss.get_provider_config("perplexity", temp_db)["model"] == "sonar"
    # No stale defaults remain.
    assert ss._DEFAULT_MODEL["anthropic"] != "claude-3-5-sonnet-latest"
