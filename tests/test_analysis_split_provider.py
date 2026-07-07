"""MAIN screen Research Notes: split-provider routing in generate_note().

SYNTHESIS (the structured note) ALWAYS runs on the chosen ``provider`` (a strong
model such as Anthropic/DeepSeek). Per-name CATALYST TRIAGE routes to a dedicated
``web_provider`` (Perplexity) when one is supplied and web-capable; else it uses
the main ``provider`` only when that provider is itself web-capable; else the
triage step runs deterministic/event-only with a "needs Perplexity" notice.

Fake providers tag every completion with ``<NAME>:<SECTION>`` by sniffing the
prompt so the test can trace which provider authored which step.
"""
from app.llm import research_notes as rn
from app.llm.base import LLMProvider


def _section_for(prompt: str) -> str:
    """Identify the generate_note prompt, mirroring the prompt-builder wording."""
    p = prompt.lower()
    if "catalyst triage" in p:
        return "TRIAGE"
    if "structured research note" in p:
        return "SYNTH"
    return "OTHER"


class _Fake(LLMProvider):
    """Returns '<NAME>:<SECTION> ...' plus a mechanical verdict for triage so a
    routed triage produces a MECHANICAL_DISLOCATION we can assert on."""

    name = "fake"

    def __init__(self, name="fake", *a, **k):
        super().__init__("fake-key", "fake-model")
        self.name = name

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        sec = _section_for(prompt)
        if sec == "TRIAGE":
            return (
                f"{self.name.upper()}:TRIAGE The web shows an index rebalance and "
                "forced passive flow; fundamentals intact, move is mechanical.\n"
                "VERDICT: MECHANICAL_DISLOCATION"
            )
        return f"{self.name.upper()}:SYNTH structured note body."


class FakeClaude(_Fake):
    """Non-web-capable synthesis model (name != perplexity)."""

    def __init__(self, *a, **k):
        super().__init__(name="anthropic")


class FakePerp(_Fake):
    """Web-capable provider (name == perplexity)."""

    def __init__(self, *a, **k):
        super().__init__(name="perplexity")


class NeedsDataPerp(FakePerp):
    """Web-capable but returns NEEDS_DATA on triage (models a null web result)."""

    def complete(self, prompt, **opts):
        if _section_for(prompt) == "TRIAGE":
            return "Nothing specific found.\nVERDICT: NEEDS_DATA"
        return f"{self.name.upper()}:SYNTH structured note body."


OS = [
    {"ticker": "AAA", "name": "Alpha", "sector": "Tech", "sub_industry": "Semis",
     "rank_z": -2.4, "z_1w": -2.4, "z_1m_ex_week": -1.0, "rsi": 24.0,
     "peer_relative_z": -1.9, "reversion_score": 0.90,
     "dislocation_type": "IDIOSYNCRATIC", "partial_history": False,
     "event_flag": False},
]
OB = []


def _cands(out):
    return {c["ticker"]: c for c in out["candidates"]}


# (a) Anthropic synthesis + Perplexity web -> synthesis authored by anthropic,
#     triage authored by perplexity (mechanical), NO 'needs Perplexity' notice.
def test_split_claude_synth_perp_web():
    out = rn.generate_note(
        FakeClaude(), OS, OS, OB, params={}, max_longs=1, max_shorts=0,
        with_news=True, web_provider=FakePerp(), asof="2026-06-19")
    assert out["error"] == ""
    # synthesis ran on the chosen (anthropic) provider
    assert out["provider"] == "anthropic"
    assert "ANTHROPIC:SYNTH" in out["markdown"]
    # triage grounded via the perplexity web provider -> mechanical, web-backed
    c = _cands(out)["AAA"]
    assert c["verdict"] == "MECHANICAL_DISLOCATION"
    assert c["source"] in ("llm", "web-event", "event+llm")
    # web fired -> no skip notice
    assert out["notice"] == ""


# (b) Anthropic synthesis, no web provider, provider not web-capable, with_news
#     -> synthesis still runs, notice set, triage falls back to non-web/event.
def test_split_claude_no_web_provider_sets_notice():
    out = rn.generate_note(
        FakeClaude(), OS, OS, OB, params={}, max_longs=1, max_shorts=0,
        with_news=True, web_provider=None, asof="2026-06-19")
    assert out["error"] == ""
    assert out["provider"] == "anthropic"
    assert "ANTHROPIC:SYNTH" in out["markdown"]
    # notice explains a Perplexity key is needed for live catalysts...
    assert out["notice"]
    assert "perplexity" in out["notice"].lower()
    # ...and names the synthesis model that DID run
    assert "anthropic" in out["notice"].lower()


# (c) Perplexity synthesis, no separate web provider -> web fires via provider
#     (back-compat with single-provider behaviour); no notice.
def test_split_perp_synth_backcompat():
    out = rn.generate_note(
        FakePerp(), OS, OS, OB, params={}, max_longs=1, max_shorts=0,
        with_news=True, web_provider=None, asof="2026-06-19")
    assert out["error"] == ""
    assert out["provider"] == "perplexity"
    # both synthesis and triage authored by perplexity
    assert "PERPLEXITY:SYNTH" in out["markdown"]
    c = _cands(out)["AAA"]
    assert c["verdict"] == "MECHANICAL_DISLOCATION"
    assert out["notice"] == ""


# (d) with_news=False + a web provider supplied -> triage does NOT hit the web,
#     no notice nag, synthesis still runs on the chosen provider.
def test_split_with_news_false_no_web_no_notice():
    out = rn.generate_note(
        FakeClaude(), OS, OS, OB, params={}, max_longs=1, max_shorts=0,
        with_news=False, web_provider=FakePerp(), asof="2026-06-19")
    assert out["error"] == ""
    assert "ANTHROPIC:SYNTH" in out["markdown"]
    # triage authored by perplexity is NOT web-grounded (with_news False) but the
    # canned mechanical verdict is deterministic here; the key assertion is that
    # no skip notice is raised when with_news was not requested.
    assert out["notice"] == ""


# (e) Anthropic synthesis + Perplexity web that returns NEEDS_DATA -> synthesis
#     still authored by anthropic, no crash, no skip notice (web DID run).
def test_split_web_needs_data_still_no_notice():
    out = rn.generate_note(
        FakeClaude(), OS, OS, OB, params={},
        max_longs=1, max_shorts=0, with_news=True, web_provider=NeedsDataPerp(),
        asof="2026-06-19")
    assert out["error"] == ""
    assert "ANTHROPIC:SYNTH" in out["markdown"]
    assert out["notice"] == ""
