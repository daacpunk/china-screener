"""Anthropic temperature-param handling: omit for models that reject it,
and auto-retry without it if the API reports it deprecated/unsupported."""
import sys
import types

import pytest

from app.llm.base import LLMError
from app.llm.anthropic_client import AnthropicProvider
from app.llm import models as M


def _install_fake_anthropic(monkeypatch, captured, raise_first_with=None):
    """Install a fake `anthropic` module whose messages.create records kwargs.

    If raise_first_with is set, the first call raises an Exception carrying that
    message; the second (retry) call succeeds.
    """
    state = {"calls": 0}

    class _Usage:
        input_tokens = 3
        output_tokens = 4

    class _Block:
        text = "pong"

    class _Msg:
        usage = _Usage()
        content = [_Block()]

    class _Messages:
        def create(self, **kwargs):
            state["calls"] += 1
            captured.append(dict(kwargs))
            if raise_first_with and state["calls"] == 1:
                raise Exception(raise_first_with)
            return _Msg()

    class _Anthropic:
        def __init__(self, api_key=None, **kwargs):
            self.api_key = api_key
            # Capture client-construction kwargs (timeout / max_retries) so tests
            # can assert our explicit timeout + retry policy.
            state["client_kwargs"] = dict(kwargs)
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return state


def test_no_temperature_for_opus_4_8(monkeypatch):
    captured = []
    _install_fake_anthropic(monkeypatch, captured)
    prov = AnthropicProvider(api_key="k", model="claude-opus-4-8")
    out = prov.complete("hi")
    assert out == "pong"
    assert "temperature" not in captured[0]  # omitted up front


def test_temperature_sent_for_sonnet_4_6(monkeypatch):
    captured = []
    _install_fake_anthropic(monkeypatch, captured)
    prov = AnthropicProvider(api_key="k", model="claude-sonnet-4-6")
    prov.complete("hi")
    assert "temperature" in captured[0]


def test_auto_retry_drops_temperature_on_deprecation(monkeypatch):
    captured = []
    # A model NOT in the no-temp set, but the API still reports it deprecated.
    _install_fake_anthropic(
        monkeypatch, captured,
        raise_first_with="Error code: 400 - `temperature` is deprecated for this model.",
    )
    prov = AnthropicProvider(api_key="k", model="claude-sonnet-4-6")
    out = prov.complete("hi")
    assert out == "pong"
    assert len(captured) == 2  # retried
    assert "temperature" in captured[0]      # first attempt had it
    assert "temperature" not in captured[1]  # retry dropped it


def test_client_has_timeout_and_no_sdk_retries(monkeypatch):
    # The client must be built with an explicit timeout (default 60s) and
    # max_retries=0 so our resilience layer controls retries, not the SDK.
    captured = []
    state = _install_fake_anthropic(monkeypatch, captured)
    prov = AnthropicProvider(api_key="k", model="claude-sonnet-4-6")
    prov.complete("hi")
    ck = state["client_kwargs"]
    assert ck.get("timeout") == 60
    assert ck.get("max_retries") == 0


def test_client_timeout_honors_opts(monkeypatch):
    captured = []
    state = _install_fake_anthropic(monkeypatch, captured)
    prov = AnthropicProvider(api_key="k", model="claude-sonnet-4-6")
    prov.complete("hi", timeout=5)
    assert state["client_kwargs"].get("timeout") == 5


def test_helper_classification():
    assert M.anthropic_supports_temperature("claude-sonnet-4-6") is True
    assert M.anthropic_supports_temperature("claude-haiku-4-5") is True
    assert M.anthropic_supports_temperature("claude-opus-4-8") is False
    assert M.anthropic_supports_temperature("claude-fable-5") is False
