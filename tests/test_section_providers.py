"""CHANGE 4 — per-section AI provider get/set + fallback to global default."""
import pytest

from app import settings_store as ss


def test_section_provider_fallback_to_global(temp_db):
    # Unset -> falls back to global default (perplexity by default).
    assert ss.get_default_provider(temp_db) == "perplexity"
    for s in ss.SECTIONS:
        assert ss.get_section_provider(s, temp_db) == "perplexity"
        assert ss.get_section_provider_raw(s, temp_db) is None
    # Change global default -> all unset sections follow.
    ss.set_default_provider("deepseek", temp_db)
    assert ss.get_section_provider("sidebar", temp_db) == "deepseek"


def test_section_provider_explicit_override(temp_db):
    ss.set_section_provider("sidebar", "anthropic", temp_db)
    ss.set_section_provider("news", "perplexity", temp_db)
    assert ss.get_section_provider("sidebar", temp_db) == "anthropic"
    assert ss.get_section_provider_raw("sidebar", temp_db) == "anthropic"
    assert ss.get_section_provider("news", temp_db) == "perplexity"
    # Others still fall back to global.
    ss.set_default_provider("deepseek", temp_db)
    assert ss.get_section_provider("per_name", temp_db) == "deepseek"


def test_get_all_section_providers(temp_db):
    ss.set_default_provider("anthropic", temp_db)
    ss.set_section_provider("portfolio", "deepseek", temp_db)
    allp = ss.get_all_section_providers(temp_db)
    assert set(allp.keys()) == set(ss.SECTIONS)
    assert allp["portfolio"] == "deepseek"
    assert allp["sidebar"] == "anthropic"  # fallback


def test_clear_section_provider(temp_db):
    ss.set_section_provider("sidebar", "anthropic", temp_db)
    ss.set_section_provider("sidebar", "", temp_db)  # clear
    assert ss.get_section_provider_raw("sidebar", temp_db) is None
    assert ss.get_section_provider("sidebar", temp_db) == ss.get_default_provider(temp_db)


def test_section_provider_validates(temp_db):
    with pytest.raises(ValueError):
        ss.set_section_provider("bogus_section", "anthropic", temp_db)
    with pytest.raises(ValueError):
        ss.set_section_provider("sidebar", "not_a_provider", temp_db)
    with pytest.raises(ValueError):
        ss.get_section_provider("bogus_section", temp_db)
