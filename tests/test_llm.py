"""Mocked LLM provider call; graceful disable; analysis never crashes."""
from app.llm import analysis as la
from app.llm.base import LLMProvider, LLMError
from app.llm.registry import build_provider, available_providers


class MockProvider(LLMProvider):
    name = "mock"

    def complete(self, prompt, **opts):
        return f"MOCK_RESPONSE for prompt of len {len(prompt)}"


class FailingProvider(LLMProvider):
    name = "failing"

    def complete(self, prompt, **opts):
        raise LLMError("simulated outage")


ROWS_OS = [{"ticker": "AAA", "name": "A", "sector": "X", "sub_industry": "Y",
            "z_1w": -2.0, "z_1m_ex_week": -1.5, "dist_from_sma": -0.2, "rsi": 22.0,
            "macd_state": "Bearish", "peer_relative_z": -1.5,
            "dislocation_type": "IDIOSYNCRATIC", "event_flag": False}]
ROWS_OB = [{"ticker": "BBB", "name": "B", "sector": "X", "sub_industry": "Z",
            "z_1w": 2.1, "z_1m_ex_week": 1.7, "dist_from_sma": 0.25, "rsi": 78.0,
            "macd_state": "Bullish", "peer_relative_z": 1.6,
            "dislocation_type": "SECTOR/MACRO/POLICY", "event_flag": True}]


def test_registry_builds_known_providers():
    assert set(available_providers()) == {"perplexity", "anthropic", "deepseek"}
    # no key -> None (graceful disable)
    assert build_provider("anthropic", "", "model") is None
    assert build_provider("unknown", "key", "m") is None
    assert build_provider("perplexity", "key", "sonar") is not None


def test_analysis_disabled_without_provider():
    res = la.analyze_rows(None, ROWS_OS, ROWS_OB)
    assert res["enabled"] is False
    assert "Settings" in res["error"]
    assert res["per_name"] == []


def test_analysis_with_mock_provider():
    prov = MockProvider(api_key="x", model="m")
    res = la.analyze_rows(prov, ROWS_OS, ROWS_OB)
    assert res["enabled"] is True
    assert res["error"] == ""
    assert len(res["per_name"]) == 2  # one per row
    assert "MOCK_RESPONSE" in res["portfolio"]
    assert all("MOCK_RESPONSE" in n["note"] for n in res["per_name"])


def test_analysis_handles_provider_errors_gracefully():
    prov = FailingProvider(api_key="x", model="m")
    res = la.analyze_rows(prov, ROWS_OS, ROWS_OB)
    # should not raise; errors captured
    assert res["enabled"] is True
    assert "simulated outage" in res["error"]
    assert res["portfolio"] == ""


def test_provider_ping_no_key():
    prov = MockProvider(api_key="", model="m")
    out = prov.ping()
    assert out["ok"] is False


def test_prompt_includes_methodology():
    p = la.build_per_name_prompt(ROWS_OS[0], "Oversold-Reversion long")
    assert "QUALITATIVE" in p and "do NOT recompute" in p
    assert "AAA" in p
