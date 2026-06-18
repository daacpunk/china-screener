"""ITEM 1 — httpx providers surface the 400 body, strip keys, parse 200."""
import httpx
import pytest

from app.llm.base import LLMError
from app.llm.deepseek import DeepSeekProvider
from app.llm.perplexity import PerplexityProvider


def _patch_client(monkeypatch, handler):
    """Force httpx.Client to use a MockTransport with the given handler."""
    real_init = httpx.Client.__init__

    def fake_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        # drop a base_url that could conflict; keep timeout
        kwargs.pop("app", None)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", fake_init)


@pytest.mark.parametrize("cls,prefix", [
    (PerplexityProvider, "Perplexity"),
    (DeepSeekProvider, "DeepSeek"),
])
def test_400_surfaces_status_and_body(monkeypatch, cls, prefix):
    body = {"error": {"type": "invalid_model", "message": "stale model id"}}

    def handler(request):
        return httpx.Response(400, json=body)

    _patch_client(monkeypatch, handler)
    prov = cls(api_key="k", model="bogus-model")
    with pytest.raises(LLMError) as ei:
        prov.complete("hi")
    msg = str(ei.value)
    assert f"{prefix} 400" in msg  # status code present
    assert "invalid_model" in msg and "stale model id" in msg  # server body present
    assert "Client error" not in msg  # NOT the old raise_for_status string


@pytest.mark.parametrize("cls", [PerplexityProvider, DeepSeekProvider])
def test_api_key_is_stripped(monkeypatch, cls):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "pong"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        })

    _patch_client(monkeypatch, handler)
    prov = cls(api_key="secret-key\n", model="m")
    assert prov.api_key == "secret-key"  # stripped in __init__
    out = prov.complete("hi")
    assert out == "pong"
    assert "\n" not in seen["auth"]
    assert seen["auth"] == "Bearer secret-key"


@pytest.mark.parametrize("cls", [PerplexityProvider, DeepSeekProvider])
def test_200_parses_content_and_usage(monkeypatch, cls):
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "hello world"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    _patch_client(monkeypatch, handler)
    prov = cls(api_key="k", model="m")
    out = prov.complete("hi")
    assert out == "hello world"
    assert prov.last_usage == {"prompt_tokens": 10, "completion_tokens": 5}


def test_ping_returns_full_error_and_model(monkeypatch):
    body = {"error": {"message": "bad key"}}

    def handler(request):
        return httpx.Response(401, json=body)

    _patch_client(monkeypatch, handler)
    prov = PerplexityProvider(api_key="k\n", model="sonar")
    res = prov.ping()
    assert res["ok"] is False
    assert res["model"] == "sonar"
    assert "Perplexity 401" in res["detail"]
    assert "bad key" in res["detail"]


def test_ping_no_key_path():
    prov = PerplexityProvider(api_key="   ", model="sonar")
    res = prov.ping()
    assert res["ok"] is False
    assert "no API key" in res["detail"]
    assert res["model"] == "sonar"
