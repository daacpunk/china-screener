"""Phase D: split-provider routing in generate_weekly_note.

SYNTHESIS (data observations + HSI narrative) runs on the chosen ``provider``;
WEB (per-mover catalysts) routes to ``web_provider`` when web-capable, else
falls back to ``provider`` only if it is web-capable, else skips with a notice.

Fake providers tag their output per section by sniffing the prompt so the test
can assert which provider authored which section.
"""
import numpy as np
import pandas as pd

from app.llm.base import LLMProvider
from app.weekly import metrics as M
from app.weekly import note as N


def _section_for(prompt: str) -> str:
    """Identify which weekly prompt this is, mirroring note.build_* wording."""
    p = prompt.lower()
    if "likely catalyst" in p or "live web / recent-news" in p:
        return "CATALYST"
    if "top-down index section" in p or "macro strategist" in p:
        return "HSI"
    return "OBS"


class _Fake(LLMProvider):
    """Returns '<NAME>:<SECTION>' so the test can trace routing."""
    name = "fake"

    def __init__(self, name="fake", *a, **k):
        super().__init__("fake-key", "fake-model")
        self.name = name

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        return f"{self.name.upper()}:{_section_for(prompt)} prose."


class FakeClaude(_Fake):
    """Non-web-capable synthesis model (name != perplexity)."""
    def __init__(self, *a, **k):
        super().__init__(name="anthropic")


class FakePerp(_Fake):
    """Web-capable provider (name == perplexity)."""
    def __init__(self, *a, **k):
        super().__init__(name="perplexity")


def _metrics():
    dates = pd.bdate_range("2026-01-01", periods=130).strftime("%Y-%m-%d").tolist()

    def recs(p, v):
        return [{"date": d, "close": float(x), "volume": float(y)}
                for d, x, y in zip(dates, p, v)]
    up = list(np.linspace(100, 118, 125)) + [119, 121, 123, 126, 130]
    dn = list(np.linspace(100, 95, 130))
    snap = {
        "asof": "2026-06-26", "stale": False, "n_stale": 1, "partial": [],
        "tickers": {"AAA-HK": recs(up, [1e6] * 125 + [3e6, 1e6, 1e6, 1e6, 1e6]),
                    "BBB-HK": recs(dn, [1e6] * 130)},
        "hsi": [{"date": d, "close": float(c)}
                for d, c in zip(dates, np.linspace(20000, 21000, 130))],
    }
    return M.compute_weekly_metrics(snap)


# (a) Claude synthesis + Perplexity web -> synthesis prose AND web catalysts,
#     no 'needs perplexity' notice. Best of both.
def test_split_claude_synth_perp_web():
    m = _metrics()
    note = N.generate_weekly_note(
        FakeClaude(), m, with_news=True, web_provider=FakePerp())
    md = note["markdown"]
    # observations + HSI narrative authored by anthropic synthesis model
    assert "ANTHROPIC:OBS" in md
    assert "ANTHROPIC:HSI" in md
    # catalysts authored by the perplexity web provider
    assert "## Catalysts (web)" in md
    assert "PERPLEXITY:CATALYST" in md
    # no skip notice (catalysts fired)
    assert note["notice"] == ""
    assert note["provider"] == "anthropic"


# (b) Claude synthesis, no web provider, provider not web-capable
#     -> synthesis present, web SKIPPED, notice set.
def test_split_claude_no_web_provider_skips_with_notice():
    m = _metrics()
    note = N.generate_weekly_note(
        FakeClaude(), m, with_news=True, web_provider=None)
    md = note["markdown"]
    assert "ANTHROPIC:OBS" in md
    assert "ANTHROPIC:HSI" in md
    assert "## Catalysts (web)" not in md
    assert "CATALYST" not in md
    assert "perplexity" in note["notice"].lower()


# (c) Perplexity synthesis, no separate web provider -> web fires via provider
#     (back-compat with the single-provider behaviour).
def test_split_perp_synth_backcompat():
    m = _metrics()
    note = N.generate_weekly_note(
        FakePerp(), m, with_news=True, web_provider=None)
    md = note["markdown"]
    assert "## Catalysts (web)" in md
    assert "PERPLEXITY:CATALYST" in md
    assert note["notice"] == ""


# (d) No synthesis provider, but a web provider exists -> tables + catalysts,
#     no crash.
def test_split_no_synth_but_web():
    m = _metrics()
    note = N.generate_weekly_note(
        None, m, with_news=True, web_provider=FakePerp())
    md = note["markdown"]
    # deterministic tables always present
    assert "## Computed metrics" in md
    # catalysts authored by the web provider
    assert "PERPLEXITY:CATALYST" in md
    # no synthesis observations section (no synthesis provider)
    assert "ANTHROPIC:OBS" not in md
    assert note["provider"] == "perplexity"
    assert note["error"] == ""


# (e) with_news=False -> no web even when a web provider is supplied.
def test_split_with_news_false_no_web():
    m = _metrics()
    note = N.generate_weekly_note(
        FakeClaude(), m, with_news=False, web_provider=FakePerp())
    md = note["markdown"]
    assert "## Catalysts (web)" not in md
    assert "CATALYST" not in md
    # synthesis still ran
    assert "ANTHROPIC:OBS" in md
    # with_news explicitly False -> no notice nag
    assert note["notice"] == ""
