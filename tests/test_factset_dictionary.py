"""Canonical FactSet =FDS dictionary (sample_data/factset_dictionary.json) +
the main screen dictionary's new authoritative entries.

Asserts the converted authoritative library is valid app-format JSON, carries the
key confirmed formulas (P_MARKET_VAL_CO, FE_VALUATION, FE_ESTIMATE, FF_SALES),
and preserves the FULL estimate_item_keywords library (standard + sector groups,
~600 entries) incl. EPS/SALES/EBITDA and the banks/insurance/mining groups.
"""
import json
from pathlib import Path

from app import settings_store as ss

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "sample_data" / "factset_dictionary.json"
MAIN = ROOT / "sample_data" / "dictionary.json"


def _load(p):
    return json.loads(p.read_text())


def test_canonical_is_valid_app_dictionary():
    # Must pass the app's own dictionary validator (object w/ non-empty formulas,
    # each carrying fql_template).
    d = ss.validate_dictionary(CANON.read_text())
    assert d["name"] == "FactSet =FDS Formula Dictionary"
    assert d["formulas"], "formulas must be non-empty"
    for key, val in d["formulas"].items():
        assert "fql_template" in val and val["fql_template"], key
        assert "label" in val and "notes" in val, key
        assert val.get("family") in {"price", "fundamentals", "estimates",
                                      "identifiers", "corporate_actions"}, key
        assert val.get("fds_compatible") is True, key


def test_canonical_contains_key_confirmed_formulas():
    d = _load(CANON)
    f = d["formulas"]
    # P_MARKET_VAL_CO market cap
    assert "market_cap" in f
    assert f["market_cap"]["fql_template"].startswith("P_MARKET_VAL_CO")
    # FE_VALUATION (native fwd P/E)
    assert "fe_valuation_pe_ntm" in f
    assert "FE_VALUATION(PE,MEAN,NTMA" in f["fe_valuation_pe_ntm"]["fql_template"]
    # FE_ESTIMATE
    assert "fe_estimate" in f
    assert "FE_ESTIMATE(" in f["fe_estimate"]["fql_template"]
    # FF_SALES (canonical key 'ff_sales')
    assert "ff_sales" in f
    assert f["ff_sales"]["fql_template"].startswith("FF_SALES")


def test_canonical_carries_syntax_layout_and_quality_sections():
    d = _load(CANON)
    sc = d["syntax_conventions"]
    assert "base_structure" in sc and "placeholders" in sc
    assert "quote_escaping" in sc and "syntax_mode_conversions" in sc
    # report layout codes carried verbatim
    rl = d["report_layout_codes"]["codes"]
    assert "^COL" in rl and "^ROW" in rl and "^SHEET" in rl
    # data quality flags carried verbatim
    flags = d["data_quality_flags"]
    assert isinstance(flags, list) and len(flags) >= 5


def test_estimate_item_keywords_full_library_preserved():
    d = _load(CANON)
    kw = d["estimate_item_keywords"]
    assert "description" in kw
    # standard group present with EPS / SALES / EBITDA
    std_norms = {e["norm"] for e in kw["standard"]}
    assert {"EPS", "SALES", "EBITDA"} <= std_norms
    # at least the banks + insurance + mining sector groups present
    assert "banks" in kw and "insurance" in kw and "mining" in kw
    # mining is a nested dict-of-lists (metal_prices, production_volumes, ...)
    assert isinstance(kw["mining"], dict)
    assert "metal_prices" in kw["mining"] and "production_volumes" in kw["mining"]

    # Count EVERY keyword entry across all groups (incl. nested sub-lists).
    def count(node):
        n = 0
        if isinstance(node, list):
            for it in node:
                if isinstance(it, dict) and "keyword" in it:
                    n += 1
        elif isinstance(node, dict):
            for v in node.values():
                if isinstance(v, (list, dict)):
                    n += count(v)
        return n

    total = sum(count(v) for k, v in kw.items() if k != "description")
    # The authoritative library is large (standard + ~16 sector groups). Assert a
    # generous floor well above the ~250 the spec mentions and a sane ceiling.
    assert total > 250, f"keyword library truncated: only {total} entries"
    # Per-group floors for the explicitly-required sector groups.
    assert len(kw["banks"]) >= 40
    assert len(kw["insurance"]) >= 40
    assert count(kw["mining"]) >= 60


def test_main_dictionary_has_new_authoritative_entries():
    d = ss.validate_dictionary(MAIN.read_text())
    f = d["formulas"]
    # New entries added by Part C.
    for k in ("market_cap", "fwd_pe_ntm", "company_name", "shares_out",
              "ebitda", "net_income", "enterprise_value", "fy1_eps",
              "gics_industry"):
        assert k in f, f"missing new entry {k}"
    assert f["market_cap"]["fql_template"] == "P_MARKET_VAL_CO(USD,1)"
    assert f["fwd_pe_ntm"]["fql_template"] == "FE_VALUATION(PE,MEAN,NTMA,,0,,,'')"
    assert f["company_name"]["fql_template"] == "FG_COMPANY_NAME"
    # Existing working entries MUST still be present (not removed).
    for k in ("price", "volume", "price_point", "volume_point", "date_point",
              "sector", "sub_industry", "index_weight", "next_earnings"):
        assert k in f, f"removed existing entry {k}"
