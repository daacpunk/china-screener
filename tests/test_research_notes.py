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
