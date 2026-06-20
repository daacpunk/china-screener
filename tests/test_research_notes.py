"""Research Notes: pure selection, prompt grounding, crash-proof orchestration,
and notes_store round-trip."""
from app import notes_store as ns
from app.llm import research_notes as rn
from app.llm.base import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, *a, **k):
        super().__init__("fake-key", "fake-model")

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        # canned triage + note text; mechanical so it becomes a tradeable rec
        return (
            "The drop coincides with an index rebalance and forced passive flow; "
            "fundamentals look intact and the move is mechanical.\n"
            "VERDICT: MECHANICAL_DISLOCATION"
        )


class NeedsDataProvider(LLMProvider):
    """Always returns NEEDS_DATA — models the blanket-NEEDS_DATA failure mode."""
    name = "fake"

    def __init__(self, *a, **k):
        super().__init__("fake-key", "fake-model")

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        return "Cannot tell why it moved.\nVERDICT: NEEDS_DATA"


class FakePerplexity(NeedsDataProvider):
    """Web-capable fake (name=='perplexity') that still returns NEEDS_DATA."""
    name = "perplexity"


def _master(rows):
    return rows


OS = [
    {"ticker": "AAA", "name": "Alpha", "sector": "Tech", "sub_industry": "Semis",
     "rank_z": -2.4, "z_1w": -2.4, "z_1m_ex_week": -1.0, "rsi": 24.0,
     "peer_relative_z": -1.9, "reversion_score": 0.90, "dislocation_type": "IDIOSYNCRATIC",
     "partial_history": False, "event_flag": False},
    {"ticker": "BBB", "name": "Beta", "sector": "Tech", "sub_industry": "Semis",
     "rank_z": -2.0, "z_1w": -2.0, "z_1m_ex_week": -1.2, "rsi": 28.0,
     "peer_relative_z": -2.5, "reversion_score": 0.90, "dislocation_type": "IDIOSYNCRATIC",
     "partial_history": False, "event_flag": False},
    {"ticker": "CCC", "name": "Gamma", "sector": "Tech", "sub_industry": "Semis",
     "rank_z": -3.0, "rsi": 20.0, "peer_relative_z": -3.0, "reversion_score": 0.70,
     "dislocation_type": "IDIOSYNCRATIC", "partial_history": True, "event_flag": False},
    {"ticker": "DDD", "name": "Delta", "sector": "Tech", "sub_industry": "Semis",
     "rank_z": -2.2, "rsi": 26.0, "peer_relative_z": -2.2, "reversion_score": 0.95,
     "dislocation_type": "SECTOR/MACRO/POLICY", "partial_history": False, "event_flag": False},
]
OB = [
    {"ticker": "ZZZ", "name": "Zeta", "sector": "Energy", "sub_industry": "Oil",
     "rank_z": 2.5, "rsi": 79.0, "peer_relative_z": 2.1, "fade_score": 0.88,
     "dislocation_type": "IDIOSYNCRATIC", "partial_history": False, "event_flag": False},
]


def test_select_candidates_deterministic_and_filters():
    sel = rn.select_candidates(_master(OS), OS, OB, max_longs=2, max_shorts=2, idio_only=True)
    long_tickers = [r["ticker"] for r in sel["longs"]]
    # CCC excluded (partial_history); DDD excluded (not idiosyncratic)
    assert "CCC" not in long_tickers
    assert "DDD" not in long_tickers
    # AAA and BBB tie on reversion_score (0.90) -> tiebreak |peer_relative_z|:
    # BBB (2.5) ranks above AAA (1.9)
    assert long_tickers == ["BBB", "AAA"]
    assert [r["ticker"] for r in sel["shorts"]] == ["ZZZ"]
    # deterministic across calls
    sel2 = rn.select_candidates(_master(OS), OS, OB, max_longs=2, max_shorts=2, idio_only=True)
    assert [r["ticker"] for r in sel2["longs"]] == long_tickers


def test_select_candidates_respects_max_and_idio_off():
    sel = rn.select_candidates(_master(OS), OS, OB, max_longs=1, max_shorts=1, idio_only=True)
    assert len(sel["longs"]) == 1 and len(sel["shorts"]) == 1
    # idio_only=False lets DDD (sector) back in (still excludes partial_history CCC)
    sel_all = rn.select_candidates(_master(OS), OS, OB, max_longs=5, idio_only=False)
    tickers = [r["ticker"] for r in sel_all["longs"]]
    assert "DDD" in tickers and "CCC" not in tickers


def test_catalyst_prompt_contains_row_values_and_methodology():
    p = rn.build_catalyst_prompt(OS[0], "long")
    assert "AAA" in p
    assert "RSI=24" in p
    assert "rank_z=-2.40" in p
    assert "do NOT recompute" in p
    assert "VERDICT:" in p
    assert "MECHANICAL_DISLOCATION" in p and "BROKEN_STORY" in p


def test_note_prompt_contains_values_and_no_recompute():
    triaged = {
        "longs": [{"row": OS[0], "side": "long", "verdict": "MECHANICAL_DISLOCATION",
                   "rationale": "mechanical move"}],
        "shorts": [{"row": OB[0], "side": "short", "verdict": "BROKEN_STORY",
                    "rationale": "guidance cut"}],
    }
    p = rn.build_note_prompt(triaged, "2026-06-19")
    assert "2026-06-19" in p
    assert "AAA" in p and "ZZZ" in p
    assert "RSI=24" in p
    assert "do NOT recompute" in p
    assert "REJECT" in p
    assert "Conviction" in p


def test_generate_note_no_provider_returns_candidates_no_raise():
    out = rn.generate_note(None, _master(OS), OS, OB, params={}, asof="2026-06-19")
    assert out["markdown"] == ""
    assert out["provider"] is None
    assert "key" in out["error"].lower()
    # still returns the deterministic selection
    assert [c["ticker"] for c in out["candidates"]] == ["BBB", "AAA", "ZZZ"]


def test_generate_note_happy_path_with_fake_provider():
    prov = FakeProvider()
    out = rn.generate_note(prov, _master(OS), OS, OB, params={}, max_longs=2,
                           max_shorts=1, idio_only=True, asof="2026-06-19")
    assert out["error"] == ""
    assert out["provider"] == "fake"
    assert out["markdown"]  # synthesized note text present
    verdicts = {c["ticker"]: c["verdict"] for c in out["candidates"]}
    assert verdicts["AAA"] == "MECHANICAL_DISLOCATION"
    assert verdicts["ZZZ"] == "MECHANICAL_DISLOCATION"


def test_parse_verdict_variants():
    assert rn._parse_verdict("blah\nVERDICT: BROKEN_STORY") == "BROKEN_STORY"
    assert rn._parse_verdict("VERDICT: needs_data") == "NEEDS_DATA"
    assert rn._parse_verdict("no label here") == "NEEDS_DATA"


def test_notes_store_round_trip(temp_db):
    cands = [{"ticker": "AAA", "side": "long"}]
    nid = ns.save_note("2026-06-19", "fake", cands, "# Note\n\nbody", db_path=temp_db)
    assert isinstance(nid, int) and nid > 0
    listed = ns.list_notes(db_path=temp_db)
    assert len(listed) == 1
    assert listed[0]["id"] == nid
    assert listed[0]["asof"] == "2026-06-19"
    assert listed[0]["provider"] == "fake"
    got = ns.get_note(nid, db_path=temp_db)
    assert got["markdown"] == "# Note\n\nbody"
    assert got["candidates"] == cands
    assert got["council"] is None
    assert ns.get_note(99999, db_path=temp_db) is None


# --- Option A: web-grounded catalyst lookup -------------------------------

def test_catalyst_prompt_with_news_adds_web_block_and_targeting():
    row = dict(OS[0], asof="2026-06-19")
    p = rn.build_catalyst_prompt(row, "long", with_news=True)
    assert "USE LIVE WEB" in p
    assert "AAA" in p and "Alpha" in p and "2026-06-19" in p
    # relaxed no-fabricate rule: only NEEDS_DATA after searching
    assert "yields nothing specific" in p
    # without with_news, no web block and the strict no-fabricate rule stays
    p0 = rn.build_catalyst_prompt(row, "long", with_news=False)
    assert "USE LIVE WEB" not in p0
    assert "do NOT fabricate a catalyst" in p0


def test_is_web_capable_true_for_perplexity_only():
    assert rn.is_web_capable(FakePerplexity()) is True
    assert rn.is_web_capable(FakeProvider()) is False
    assert rn.is_web_capable(None) is False


def test_notice_set_when_with_news_but_provider_not_web_capable():
    out = rn.generate_note(FakeProvider(), _master(OS), OS, OB, params={},
                           with_news=True, asof="2026-06-19")
    assert out["notice"]
    assert "Perplexity" in out["notice"]


def test_no_notice_when_provider_web_capable():
    out = rn.generate_note(FakePerplexity(), _master(OS), OS, OB, params={},
                           with_news=True, asof="2026-06-19")
    assert out["notice"] == ""


# --- Option C: deterministic event tagging --------------------------------

EVENT_OS = [
    dict(OS[0], ticker="EVT", name="EventCo", event_flag=True,
         event_date="2026-06-29"),
]


def test_event_flag_pretag_mechanical_even_when_llm_says_needs_data():
    # No web -> LLM not even called for an event-flagged name; pre-tag stands.
    out = rn.generate_note(NeedsDataProvider(), _master(EVENT_OS), EVENT_OS, [],
                           params={}, max_longs=1, max_shorts=0, asof="2026-06-19")
    c = {x["ticker"]: x for x in out["candidates"]}["EVT"]
    assert c["verdict"] == "MECHANICAL_DISLOCATION"
    assert c["source"] == "event"
    assert c["event_date"] == "2026-06-29"


def test_event_flag_with_web_overrides_llm_needs_data():
    # Web on + web-capable -> LLM runs, returns NEEDS_DATA, but event biases to
    # MECHANICAL_DISLOCATION (event-backed) rather than PASS.
    out = rn.generate_note(FakePerplexity(), _master(EVENT_OS), EVENT_OS, [],
                           params={}, max_longs=1, max_shorts=0,
                           with_news=True, asof="2026-06-19")
    c = {x["ticker"]: x for x in out["candidates"]}["EVT"]
    assert c["verdict"] == "MECHANICAL_DISLOCATION"
    assert c["source"] == "event+llm"


def test_non_event_no_web_needs_data_stays_pass():
    # No event flag, no web access, LLM says NEEDS_DATA -> honest NEEDS_DATA
    # (note synthesis renders this as PASS); verdict is NOT mechanical.
    out = rn.generate_note(NeedsDataProvider(), _master(OS), OS, OB, params={},
                           max_longs=2, max_shorts=1, asof="2026-06-19")
    verdicts = {c["ticker"]: c["verdict"] for c in out["candidates"]}
    assert verdicts["AAA"] == "NEEDS_DATA"
    sources = {c["ticker"]: c["source"] for c in out["candidates"]}
    assert sources["AAA"] == "llm"


# --- Option B: web-detected mechanical event upgrades NEEDS_DATA ----------

class WebExDivProvider(LLMProvider):
    """Web-capable fake: describes an ex-dividend yet cautiously votes NEEDS_DATA."""
    name = "perplexity"

    def __init__(self, *a, **k):
        super().__init__("fake-key", "fake-model")

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        return (
            "The stock went ex-dividend on June 12 [1][7], which mechanically "
            "lowers the price; fundamentals appear intact but I cannot fully "
            "confirm the magnitude.\n"
            "VERDICT: NEEDS_DATA"
        )


class WebBrokenDivProvider(LLMProvider):
    """Web-capable fake: BROKEN_STORY verdict whose text mentions 'dividend'."""
    name = "perplexity"

    def __init__(self, *a, **k):
        super().__init__("fake-key", "fake-model")

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        return (
            "Management cut the dividend amid a guidance reduction and structural "
            "demand decline — this is a deteriorating story.\n"
            "VERDICT: BROKEN_STORY"
        )


def test_detect_mechanical_event_matches_representative_strings():
    assert rn.detect_mechanical_event("went ex-dividend on June 12")
    assert rn.detect_mechanical_event("part of the MSCI index rebalance")
    assert rn.detect_mechanical_event("a large share placement was announced")
    assert rn.detect_mechanical_event("driven by a block trade overnight")
    assert rn.detect_mechanical_event("the spin-off completed last week")


def test_detect_mechanical_event_none_for_generic_and_empty():
    assert rn.detect_mechanical_event("the stock fell for unclear reasons") is None
    assert rn.detect_mechanical_event("") is None
    assert rn.detect_mechanical_event(None) is None


def test_web_needs_data_with_mechanical_event_upgrades_to_mechanical():
    out = rn.generate_note(WebExDivProvider(), _master(OS), OS, OB, params={},
                           max_longs=1, max_shorts=0, with_news=True,
                           asof="2026-06-19")
    c = {x["ticker"]: x for x in out["candidates"]}["BBB"]
    assert c["verdict"] == "MECHANICAL_DISLOCATION"
    assert c["source"] == "web-event"


def test_web_off_needs_data_with_event_text_stays_needs_data():
    # Same rationale text, but with_news=False -> honest NEEDS_DATA, no upgrade.
    out = rn.generate_note(WebExDivProvider(), _master(OS), OS, OB, params={},
                           max_longs=1, max_shorts=0, with_news=False,
                           asof="2026-06-19")
    c = {x["ticker"]: x for x in out["candidates"]}["BBB"]
    assert c["verdict"] == "NEEDS_DATA"
    assert c["source"] == "llm"


def test_non_web_provider_needs_data_with_event_text_no_upgrade():
    # Provider not web-capable even with with_news -> no upgrade.
    out = rn.generate_note(NeedsDataProvider(), _master(OS), OS, OB, params={},
                           max_longs=1, max_shorts=0, with_news=True,
                           asof="2026-06-19")
    c = {x["ticker"]: x for x in out["candidates"]}["BBB"]
    assert c["verdict"] == "NEEDS_DATA"
    assert c["source"] == "llm"


def test_web_needs_data_no_mechanical_keywords_stays_needs_data():
    out = rn.generate_note(FakePerplexity(), _master(OS), OS, OB, params={},
                           max_longs=1, max_shorts=0, with_news=True,
                           asof="2026-06-19")
    c = {x["ticker"]: x for x in out["candidates"]}["BBB"]
    assert c["verdict"] == "NEEDS_DATA"
    assert c["source"] == "llm"


def test_web_broken_story_with_dividend_text_never_upgraded():
    out = rn.generate_note(WebBrokenDivProvider(), _master(OS), OS, OB, params={},
                           max_longs=1, max_shorts=0, with_news=True,
                           asof="2026-06-19")
    c = {x["ticker"]: x for x in out["candidates"]}["BBB"]
    assert c["verdict"] == "BROKEN_STORY"
    assert c["source"] == "llm"
