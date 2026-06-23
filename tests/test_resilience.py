"""Tests for retry+backoff, provider fallback, and concurrent analyze_rows."""
import pytest

from app.llm import analysis as la
from app.llm import resilience as rz
from app.llm.base import LLMError, LLMProvider


class FakeProvider(LLMProvider):
    """Fails the first ``fail_times`` calls with ``exc``, then returns ``text``."""

    def __init__(self, name="fake", *, fail_times=0, exc=None, text="OK"):
        super().__init__(api_key="x", model="m")
        self.name = name
        self.fail_times = fail_times
        self.exc = exc or LLMError("Error code: 529 ... Overloaded")
        self.text = text
        self.calls = 0

    def complete(self, prompt, **opts):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.text


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rz.time, "sleep", lambda *_a, **_k: None)


# ---- (a) is_retryable detection ------------------------------------------

def test_is_retryable_true_signals():
    assert rz.is_retryable(LLMError("Error code: 529 ... Overloaded"))
    assert rz.is_retryable(LLMError("429 rate limit exceeded"))
    assert rz.is_retryable(LLMError("DeepSeek 503: service unavailable"))


def test_is_retryable_false_permanent():
    assert not rz.is_retryable(LLMError("invalid api key"))
    assert not rz.is_retryable(LLMError("401 authentication failed"))
    assert not rz.is_retryable(LLMError("400 bad request"))


def test_is_retryable_status_attribute():
    e = LLMError("boom")
    e.status_code = 529
    assert rz.is_retryable(e)
    e2 = LLMError("boom")
    e2.status_code = 401
    assert not rz.is_retryable(e2)


def test_auth_beats_retry_signal():
    # Both an auth signal and a retry token present -> permanent (no retry).
    assert not rz.is_retryable(LLMError("401 invalid api key (also timeout)"))


# ---- (b) retry then succeed ----------------------------------------------

def test_complete_with_retry_recovers():
    p = FakeProvider(fail_times=2, text="recovered")
    out = rz.complete_with_retry(p, "hi", max_attempts=4)
    assert out == "recovered"
    assert p.calls == 3


# ---- (c) gives up after max_attempts -------------------------------------

def test_complete_with_retry_gives_up():
    p = FakeProvider(fail_times=99)
    with pytest.raises(LLMError):
        rz.complete_with_retry(p, "hi", max_attempts=3)
    assert p.calls == 3


# ---- (d) non-retryable fails after 1 attempt -----------------------------

def test_complete_with_retry_no_retry_on_auth():
    p = FakeProvider(fail_times=99, exc=LLMError("invalid api key"))
    with pytest.raises(LLMError):
        rz.complete_with_retry(p, "hi", max_attempts=4)
    assert p.calls == 1


# ---- (e) fallback --------------------------------------------------------

def test_fallback_uses_secondary():
    primary = FakeProvider(name="anthropic", fail_times=99)
    secondary = FakeProvider(name="deepseek", fail_times=0, text="from-secondary")
    text, used = rz.complete_with_fallback(
        primary, "hi", fallback_providers=[secondary], max_attempts=2,
    )
    assert text == "from-secondary"
    assert used == "deepseek"


def test_fallback_not_used_on_auth_error():
    primary = FakeProvider(name="anthropic", fail_times=99, exc=LLMError("invalid api key"))
    secondary = FakeProvider(name="deepseek", text="should-not-run")
    with pytest.raises(LLMError):
        rz.complete_with_fallback(primary, "hi", fallback_providers=[secondary], max_attempts=3)
    assert secondary.calls == 0


# ---- (f) analyze_rows with fallback --------------------------------------

_OS = [{"ticker": "AAA", "name": "A", "sector": "X", "sub_industry": "Y",
        "z_1w": -2.0, "rsi": 22.0, "peer_relative_z": -1.5,
        "dislocation_type": "IDIOSYNCRATIC", "event_flag": False}]
_OB = [{"ticker": "BBB", "name": "B", "sector": "X", "sub_industry": "Z",
        "z_1w": 2.1, "rsi": 78.0, "peer_relative_z": 1.6,
        "dislocation_type": "IDIOSYNCRATIC", "event_flag": False}]


def test_analyze_rows_fallback_annotates(monkeypatch):
    monkeypatch.setattr(la, "_log_usage", lambda *a, **k: None)
    primary = FakeProvider(name="anthropic", fail_times=99)
    secondary = FakeProvider(name="deepseek", fail_times=0, text="GOOD")
    res = la.analyze_rows(
        primary, _OS, _OB, max_names=6, max_workers=2,
        fallback_providers=[secondary],
    )
    assert res["enabled"] is True
    assert res["error"] == ""
    assert len(res["per_name"]) == 2
    assert all("GOOD" in n["note"] for n in res["per_name"])
    assert all("[via deepseek]" in n["note"] for n in res["per_name"])
    assert "GOOD" in res["portfolio"]
