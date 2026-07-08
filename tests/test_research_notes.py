"""Research Notes: pure selection, prompt grounding, crash-proof orchestration,
and notes_store round-trip."""
import time

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


# --- Concurrency: parallelized per-name triage (ThreadPool, max_workers=4) ---
#
# Regression guard for the 5+5 timeout bug: the per-name catalyst triage used to
# run SERIALLY, so 10 web-grounded calls + synthesis exceeded the HTTP request
# timeout. It is now dispatched through a bounded ThreadPoolExecutor. These
# tests prove (a) it actually runs concurrently, (b) order is preserved, (c) a
# raising provider still yields a candidate, and (d) event tagging survives
# concurrency.

_PER_CALL_SLEEP = 0.2


def _wide_universe(n_long: int, n_short: int):
    """Build n_long idiosyncratic oversold + n_short idiosyncratic overbought
    rows with strictly decreasing scores so selection order is deterministic."""
    oversold = []
    for i in range(n_long):
        oversold.append({
            "ticker": f"L{i:02d}", "name": f"Long{i}", "sector": "Tech",
            "sub_industry": "Semis", "rank_z": -2.0 - i * 0.01, "rsi": 25.0,
            "peer_relative_z": -2.0, "reversion_score": 0.99 - i * 0.01,
            "dislocation_type": "IDIOSYNCRATIC", "partial_history": False,
            "event_flag": False,
        })
    overbought = []
    for i in range(n_short):
        overbought.append({
            "ticker": f"S{i:02d}", "name": f"Short{i}", "sector": "Energy",
            "sub_industry": "Oil", "rank_z": 2.0 + i * 0.01, "rsi": 78.0,
            "peer_relative_z": 2.0, "fade_score": 0.99 - i * 0.01,
            "dislocation_type": "IDIOSYNCRATIC", "partial_history": False,
            "event_flag": False,
        })
    return oversold, overbought


class SleepyMechProvider(LLMProvider):
    """Synthesis provider: complete() sleeps ~0.2s and returns a full note /
    mechanical triage verdict. Non-web-capable (used for note synthesis)."""
    name = "fake"

    def __init__(self, *a, **k):
        super().__init__("fake-key", "fake-model")

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        time.sleep(_PER_CALL_SLEEP)
        return (
            "The drop coincides with an index rebalance and forced passive "
            "flow; fundamentals look intact and the move is mechanical.\n"
            "VERDICT: MECHANICAL_DISLOCATION"
        )


class SleepyPerp(SleepyMechProvider):
    """Web-capable sleepy fake (name=='perplexity') so triage actually runs
    the LLM path (with_news). Each call sleeps ~0.2s."""
    name = "perplexity"


def test_generate_note_5x5_runs_concurrently_and_completes():
    oversold, overbought = _wide_universe(5, 5)
    web = SleepyPerp()
    synth = SleepyMechProvider()
    t0 = time.time()
    out = rn.generate_note(
        synth, oversold + overbought, oversold, overbought, params={},
        max_longs=5, max_shorts=5, idio_only=True, with_news=True,
        asof="2026-07-08", web_provider=web,
    )
    elapsed = time.time() - t0
    # A full note and all 10 candidates triaged.
    assert out["error"] == ""
    assert out["markdown"]
    assert len(out["candidates"]) == 10
    verdicts = {c["ticker"]: c["verdict"] for c in out["candidates"]}
    assert all(v == "MECHANICAL_DISLOCATION" for v in verdicts.values())
    # 10 triage calls sleeping 0.2s each would take >=2.0s serially; with
    # max_workers=4 the triage wall-clock is ~ceil(10/4)*0.2 = 0.6s plus one
    # synthesis call (~0.2s). Assert clearly below the serial 10*0.2s to prove
    # concurrency.
    assert elapsed < _PER_CALL_SLEEP * 10 * 0.6, (
        f"triage did not run concurrently: {elapsed:.2f}s"
    )


def test_generate_note_5x5_order_matches_serial_baseline():
    """Ordering preserved: verdicts/sources come back in the same
    longs-then-shorts order as a serial baseline computed by calling the pure
    worker directly per name."""
    oversold, overbought = _wide_universe(5, 5)
    web = SleepyPerp()
    synth = SleepyMechProvider()
    out = rn.generate_note(
        synth, oversold + overbought, oversold, overbought, params={},
        max_longs=5, max_shorts=5, idio_only=True, with_news=True,
        asof="2026-07-08", web_provider=web,
    )
    # Serial baseline: mirror the split-provider routing generate_note uses,
    # then call the worker per name in longs-then-shorts order.
    sel = rn.select_candidates(oversold + overbought, oversold, overbought,
                               max_longs=5, max_shorts=5, idio_only=True)
    baseline = []
    for side, key in (("long", "longs"), ("short", "shorts")):
        for r in sel[key]:
            res = rn._triage_one(
                r, side, with_news=True, web_capable=True, web_runner=web,
                provider=synth, triage_fallbacks=[],
            )
            baseline.append((r["ticker"], res["entry"]["verdict"],
                             res["entry"]["source"]))
    got = [(c["ticker"], c["verdict"], c["source"]) for c in out["candidates"]]
    assert got == baseline


class RaisingPerp(LLMProvider):
    """Web-capable fake whose complete() always raises."""
    name = "perplexity"

    def __init__(self, *a, **k):
        super().__init__("fake-key", "fake-model")

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        raise RuntimeError("boom: web triage exploded")


def test_generate_note_worker_raise_still_yields_candidate():
    """A worker whose triage provider raises still yields a candidate
    (NEEDS_DATA / error captured); the pool does not die and synthesis runs."""
    oversold, overbought = _wide_universe(3, 2)
    out = rn.generate_note(
        SleepyMechProvider(), oversold + overbought, oversold, overbought,
        params={}, max_longs=3, max_shorts=2, idio_only=True, with_news=True,
        asof="2026-07-08", web_provider=RaisingPerp(),
    )
    # All 5 candidates present despite every triage call raising.
    assert len(out["candidates"]) == 5
    for c in out["candidates"]:
        assert c["verdict"] == "NEEDS_DATA"
        assert c["source"] == "llm"
    # Errors captured, one per name; note synthesis still produced text.
    assert "boom" in out["error"]
    assert out["error"].count("boom") == 5
    assert out["markdown"]


# --- Completeness guarantee: every selected candidate gets a subsection ------
#
# The synthesis model (esp. faster ones) often omits PASS/REJECT names even
# though instructed to write one subsection per candidate. generate_note now
# runs a deterministic COMPLETENESS PASS that appends a fallback subsection for
# any omitted candidate, and builds the WHOLE note deterministically when
# synthesis returns empty. These tests lock that guarantee in.


def test_missing_candidates_returns_omitted_in_order_with_base_ticker_match():
    triaged = {
        "longs": [
            {"row": {"ticker": "AAA"}, "side": "long", "verdict": "NEEDS_DATA"},
            {"row": {"ticker": "BBB"}, "side": "long", "verdict": "NEEDS_DATA"},
            {"row": {"ticker": "3360-HK"}, "side": "long", "verdict": "NEEDS_DATA"},
            {"row": {"ticker": "DDD"}, "side": "long", "verdict": "NEEDS_DATA"},
        ],
        "shorts": [
            {"row": {"ticker": "YYY"}, "side": "short", "verdict": "NEEDS_DATA"},
            {"row": {"ticker": "ZZZ"}, "side": "short", "verdict": "NEEDS_DATA"},
        ],
    }
    # Markdown mentions only AAA and 3360 (base-number of 3360-HK).
    md = "### AAA long\nsome text\n### Company (3360) short\nmore text"
    missing = rn._missing_candidates(md, triaged)
    tickers = [m["row"]["ticker"] for m in missing]
    # AAA present; 3360-HK present via base-number match; the other 4 missing
    # in original longs-then-shorts order.
    assert tickers == ["BBB", "DDD", "YYY", "ZZZ"]


class OnlyFirstLongProvider(LLMProvider):
    """Triage returns MECHANICAL; note SYNTHESIS writes ONLY the first long
    (uses a distinctive long ticker prefix) and omits every other name."""
    name = "fake"

    def __init__(self, *a, **k):
        super().__init__("fake-key", "fake-model")

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        # Note-synthesis prompts contain the labeled-parts instruction; triage
        # prompts contain the VERDICT instruction. Distinguish on that.
        if "**Recommendation:**" in prompt:
            # Synthesis: mention ONLY the first long ticker (L00), omit the rest.
            return (
                "Research note as of 2026-07-08.\n\n"
                "## Long candidates\n\n"
                "### Long0 (L00) — LONG candidate\n"
                "- **Recommendation:** LONG\n"
                "- **Setup:** oversold reversion.\n"
            )
        return (
            "Index rebalance and forced flow; mechanical.\n"
            "VERDICT: MECHANICAL_DISLOCATION"
        )


def test_generate_note_backfills_every_omitted_candidate():
    oversold, overbought = _wide_universe(3, 3)
    out = rn.generate_note(
        OnlyFirstLongProvider(), oversold + overbought, oversold, overbought,
        params={}, max_longs=3, max_shorts=3, idio_only=True, asof="2026-07-08",
    )
    md = out["markdown"]
    # Every selected ticker appears in the final markdown.
    for c in out["candidates"]:
        assert c["ticker"] in md, f"{c['ticker']} missing from note"
    # The omitted names were backfilled under an Additional candidates section.
    assert "## Additional candidates" in md
    # First long (mentioned by synthesis) is NOT double-written in backfill.
    assert md.count("### Long0 (L00)") == 1


class EmptySynthProvider(LLMProvider):
    """Triage MECHANICAL; note synthesis returns an EMPTY string."""
    name = "fake"

    def __init__(self, *a, **k):
        super().__init__("fake-key", "fake-model")

    @property
    def available(self):
        return True

    def complete(self, prompt, **opts):
        if "**Recommendation:**" in prompt:
            return ""  # synthesis produced nothing
        return (
            "Index rebalance and forced flow; mechanical.\n"
            "VERDICT: MECHANICAL_DISLOCATION"
        )


def test_generate_note_empty_synthesis_builds_full_deterministic_note():
    oversold, overbought = _wide_universe(2, 2)
    out = rn.generate_note(
        EmptySynthProvider(), oversold + overbought, oversold, overbought,
        params={}, max_longs=2, max_shorts=2, idio_only=True, asof="2026-07-08",
    )
    md = out["markdown"]
    assert md  # not empty despite synthesis returning ""
    # Full deterministic note: as-of line + grouped sections + every ticker.
    assert "2026-07-08" in md
    assert "## Long candidates" in md and "## Short candidates" in md
    for c in out["candidates"]:
        assert c["ticker"] in md, f"{c['ticker']} missing from note"


def test_render_candidate_fallback_recommendation_and_na_safe():
    # MECHANICAL_DISLOCATION long -> LONG; short -> SHORT.
    long_mech = {"row": {"ticker": "AAA", "name": "Alpha", "rank_z": -2.4,
                         "rsi": 24.0, "peer_relative_z": -1.9,
                         "dislocation_type": "IDIOSYNCRATIC"},
                 "side": "long", "verdict": "MECHANICAL_DISLOCATION",
                 "rationale": "ex-dividend", "source": "web-event"}
    s = rn._render_candidate_fallback(long_mech)
    assert "Alpha (AAA)" in s and "LONG candidate" in s
    assert "**Recommendation:** LONG" in s
    assert "Med/High" in s  # web-event source

    short_mech = dict(long_mech, side="short")
    assert "**Recommendation:** SHORT" in rn._render_candidate_fallback(short_mech)

    # NEEDS_DATA and BROKEN_STORY -> PASS.
    nd = dict(long_mech, verdict="NEEDS_DATA", rationale="", source="llm")
    s_nd = rn._render_candidate_fallback(nd)
    assert "**Recommendation:** PASS" in s_nd
    assert "No specific catalyst identified." in s_nd
    assert "**Conviction:** Low" in s_nd

    bs = dict(long_mech, verdict="BROKEN_STORY")
    assert "**Recommendation:** PASS" in rn._render_candidate_fallback(bs)

    # n/a-safe: missing/None numeric fields never raise and render "n/a".
    empty = {"row": {"ticker": "XXX", "rank_z": None, "rsi": "bad",
                     "peer_relative_z": None, "dislocation_type": None},
             "side": "long", "verdict": "NEEDS_DATA"}
    s_empty = rn._render_candidate_fallback(empty)
    assert "n/a" in s_empty and "XXX" in s_empty


def test_generate_note_event_flag_mechanical_under_concurrency():
    """An event-flagged name still tags MECHANICAL_DISLOCATION source=event
    under the concurrent path (no web, LLM not called for the event name)."""
    event_rows = [
        dict(_wide_universe(1, 0)[0][0], ticker="EVT", name="EventCo",
             event_flag=True, event_date="2026-06-29"),
    ]
    # Add a few plain names so the pool has multiple concurrent tasks.
    extra_os, extra_ob = _wide_universe(3, 2)
    oversold = event_rows + extra_os
    out = rn.generate_note(
        NeedsDataProvider(), oversold + extra_ob, oversold, extra_ob,
        params={}, max_longs=4, max_shorts=2, idio_only=True,
        asof="2026-07-08",
    )
    c = {x["ticker"]: x for x in out["candidates"]}["EVT"]
    assert c["verdict"] == "MECHANICAL_DISLOCATION"
    assert c["source"] == "event"
    assert c["event_date"] == "2026-06-29"
