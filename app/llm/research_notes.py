"""Research Notes: select candidates -> per-name catalyst triage -> note.

PURE prompt-building + orchestration. Mirrors analysis.py conventions: every
LLM path is key-gated and crash-proof — if a provider is missing or errors, a
structured result is returned (never raises, never breaks the screen). Usage is
logged via the same best-effort _log_usage pattern.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import LLMProvider
from .prompts import _METHODOLOGY, _name_ticker_label, _row_line
from .resilience import complete_with_fallback, complete_with_retry


# Concrete mechanical-event phrases. If web-grounded triage describes one of
# these in its rationale, the move is a tradeable mechanical/technical
# dislocation by construction — even when the cautious LLM still labels it
# NEEDS_DATA. Order matters only for which matched phrase is reported first;
# matching is case-insensitive with loose hyphen/space/plural tolerance.
_MECHANICAL_EVENT_PATTERNS: List[str] = [
    # Dividends / distributions
    "ex-dividend", "ex dividend", "ex-div", "ex-date", "ex date", "goes ex",
    "dividend record date", "dividend payment", "special dividend",
    "scrip dividend", "scrip",
    # Index / passive flow
    "index inclusion", "index exclusion", "index rebalance", "rebalancing",
    "rebalance", "added to the index", "added to index", "removed from the index",
    "removed from index", "index reconstitution", "float adjustment",
    "weighting change", "msci rebalance", "ftse", "msci", "sse 180",
    # Supply / forced flow
    "share placement", "placement", "placing", "block trade", "block sale",
    "secondary offering", "follow-on", "forced selling", "forced flow",
    "margin call", "liquidation", "fund redemption", "rights issue",
    "share buyback", "buyback", "repurchase", "tender",
    # Corporate structure / capital actions
    "spin-off", "spinoff", "spin off", "capital return", "share consolidation",
    "stock split", "lock-up expiry", "lockup expiry", "lock up expiry",
]


def detect_mechanical_event(text: Optional[str]) -> Optional[str]:
    """Scan triage rationale for a concrete mechanical-event phrase.

    Returns the first matched phrase (for provenance) or None. Matching is
    case-insensitive and tolerant of hyphen/space variants and simple plurals.
    Safe on None/empty input.
    """
    if not text:
        return None
    hay = str(text).lower()
    for phrase in _MECHANICAL_EVENT_PATTERNS:
        # Treat hyphens and spaces in the phrase as interchangeable whitespace/
        # hyphen, and allow an optional trailing 's' for simple plurals.
        sep = r"[\s\-]+"
        parts = re.split(r"[\s\-]+", phrase)
        body = sep.join(re.escape(p) for p in parts if p)
        pat = r"(?<![a-z0-9])" + body + r"s?(?![a-z0-9])"
        if re.search(pat, hay):
            return phrase
    return None


def _log_usage(provider: Optional[LLMProvider], section: str, ok: bool, note: str = "") -> None:
    """Best-effort usage logging. NEVER raises / breaks the screen."""
    try:
        from .. import settings_store as ss
        ss.log_usage(
            getattr(provider, "name", ""),
            getattr(provider, "model", "") or "",
            section,
            getattr(provider, "last_usage", None) if ok else None,
            ok=ok,
            note=note,
        )
    except Exception:
        pass


def is_web_capable(provider: Optional[LLMProvider]) -> bool:
    """True when the provider can ground answers in live web search.

    The Perplexity Sonar provider is inherently web-grounded; everything else
    (Anthropic, DeepSeek, fakes) is not. Checks the provider ``name`` so a fake
    provider declaring name=="perplexity" is treated as web-capable in tests.
    """
    if provider is None:
        return False
    if getattr(provider, "web_capable", False):
        return True
    return str(getattr(provider, "name", "")).lower() == "perplexity"


def _abs(x: Any) -> float:
    try:
        return abs(float(x))
    except Exception:
        return 0.0


def _score(r: Dict[str, Any], key: str) -> float:
    try:
        v = r.get(key)
        return float(v) if v is not None else float("-inf")
    except Exception:
        return float("-inf")


def select_candidates(
    master: List[Dict[str, Any]],
    oversold: List[Dict[str, Any]],
    overbought: List[Dict[str, Any]],
    max_longs: int = 2,
    max_shorts: int = 2,
    idio_only: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """PURE candidate selection (no LLM).

    Longs come from oversold (reversion), shorts from overbought (fade). When
    ``idio_only`` keep only dislocation_type == IDIOSYNCRATIC. Always exclude
    partial_history rows. Longs are ranked by reversion_score desc then
    |peer_relative_z| desc; shorts by fade_score desc then |peer_relative_z|
    desc. Returns the top ``max_longs`` / ``max_shorts``.
    """
    def _eligible(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for r in rows or []:
            if r.get("partial_history"):
                continue
            if idio_only and r.get("dislocation_type") != "IDIOSYNCRATIC":
                continue
            out.append(r)
        return out

    longs = sorted(
        _eligible(oversold),
        key=lambda r: (_score(r, "reversion_score"), _abs(r.get("peer_relative_z"))),
        reverse=True,
    )[: max(0, int(max_longs))]
    shorts = sorted(
        _eligible(overbought),
        key=lambda r: (_score(r, "fade_score"), _abs(r.get("peer_relative_z"))),
        reverse=True,
    )[: max(0, int(max_shorts))]
    return {"longs": longs, "shorts": shorts}


def _event_line(row: Dict[str, Any]) -> str:
    """Deterministic corporate-event hint surfaced explicitly to the model."""
    ed = row.get("event_date")
    ed_txt = ed if (ed not in (None, "")) else "(none)"
    return f"Known corporate event: event_flag={bool(row.get('event_flag'))}, event_date={ed_txt}"


def build_catalyst_prompt(row: Dict[str, Any], side: str, with_news: bool = False) -> str:
    """Per-name catalyst-triage prompt.

    The model classifies the move as MECHANICAL_DISLOCATION (tradeable
    technical/mechanical move — e.g. ex-dividend, index rebalance, forced flow),
    BROKEN_STORY (structural/fundamental deterioration -> reject), or NEEDS_DATA
    (cannot determine -> do not fabricate). Reuses _METHODOLOGY so the model does
    NOT recompute signals. Asks for a 2-3 sentence rationale plus the verdict on
    its own line as ``VERDICT: <LABEL>``.

    When ``with_news`` is True the prompt instructs a web-capable model to look up
    the LIKELY reason for the move (ex-dividend, index rebalance, earnings, M&A,
    policy/regulatory news, forced flow) and to ground the verdict in what it
    finds — the "do not fabricate" rule is relaxed to "ground in web findings;
    only return NEEDS_DATA if web search yields nothing specific" so the model is
    EXPECTED to look things up rather than defaulting to NEEDS_DATA.
    """
    side_label = "LONG (oversold-reversion)" if side == "long" else "SHORT (overbought-fade)"
    asof = row.get("asof") or row.get("as_of") or "the screen as-of date"
    nofab = (
        "- NEEDS_DATA: you cannot determine the cause from the information available "
        "— do NOT fabricate a catalyst.\n\n"
    )
    if with_news:
        nofab = (
            "- NEEDS_DATA: only after live web/recent-news search yields nothing "
            "specific about why this ticker moved over the lookback. Ground your "
            "catalyst in what you actually find via web search; do not default to "
            "NEEDS_DATA without searching first.\n\n"
        )
    web_block = ""
    if with_news:
        web_block = (
            "USE LIVE WEB / RECENT-NEWS CONTEXT: search the web to determine WHY "
            f"{_name_ticker_label(row)} — sector {row.get('sector')}, "
            f"as of {asof} — dislocated over the lookback window. Look specifically "
            "for: ex-dividend / ex-date, index inclusion/exclusion or rebalance, "
            "earnings or guidance, M&A, regulatory/policy news, and share "
            "placement / forced or passive flow. Cite the catalyst briefly, THEN "
            "classify. Do NOT recompute the in-app signals.\n\n"
        )
    return (
        f"{_METHODOLOGY}\n\n"
        f"You are an equity strategist running CATALYST TRIAGE on a single name "
        f"being considered as a {side_label}. Decide whether the dislocation is a "
        f"tradeable mechanical/technical move or a broken fundamental story.\n\n"
        f"{web_block}"
        "Classify into exactly one of:\n"
        "- MECHANICAL_DISLOCATION: a tradeable technical/mechanical move "
        "(e.g. ex-dividend, index rebalance, forced/passive flow, options/expiry, "
        "a one-off liquidity air-pocket) where mean-reversion is reasonable.\n"
        "- BROKEN_STORY: structural or fundamental deterioration (guidance cut, "
        "fraud, regulatory/policy break, secular decline) — REJECT, do not trade the bounce.\n"
        f"{nofab}"
        "Do NOT recompute any signals; the values below were computed in-app. "
        "Give a 2-3 sentence rationale, then output the "
        "verdict label on its OWN line in exactly this form:\n"
        "VERDICT: <MECHANICAL_DISLOCATION|BROKEN_STORY|NEEDS_DATA>\n\n"
        f"{_row_line(row)}\n"
        f"{_event_line(row)}\n"
    )


def _verdict_block(c: Dict[str, Any]) -> str:
    row = c.get("row", {})
    src = c.get("source")
    ed = c.get("event_date")
    extra = f" source={src}" if src else ""
    if ed:
        extra += f" event_date={ed}"
    return (
        f"{_row_line(row)}\n"
        f"  side={c.get('side')} triage_verdict={c.get('verdict')}{extra}\n"
        f"  triage_rationale: {c.get('rationale') or '(none)'}"
    )


def build_note_prompt(candidates_with_triage: Dict[str, List[Dict[str, Any]]], asof: Any) -> str:
    """Assemble the full structured research note in markdown.

    ``candidates_with_triage`` is {"longs":[...], "shorts":[...]} where each entry
    is {"row":..., "side":..., "verdict":..., "rationale":...}. For every
    recommended name include: Recommendation (LONG/SHORT/PASS), Setup (signal in
    plain English), Catalyst & timing, Risks, Conviction (High/Med/Low). Any
    candidate whose triage verdict is BROKEN_STORY or NEEDS_DATA must get an
    explicit short REJECT rationale. Grounded ONLY in the provided rows + triage.
    """
    longs = candidates_with_triage.get("longs", [])
    shorts = candidates_with_triage.get("shorts", [])
    long_lines = "\n".join(_verdict_block(c) for c in longs) or "(none)"
    short_lines = "\n".join(_verdict_block(c) for c in shorts) or "(none)"
    return (
        f"{_METHODOLOGY}\n\n"
        f"You are an equity strategist writing a STRUCTURED research note, as of {asof}.\n"
        "Start the note with a top line stating the as-of date. Then, for EACH "
        "candidate below, write a markdown subsection with these labeled parts:\n"
        "- **Recommendation:** LONG, SHORT, or PASS\n"
        "- **Setup:** the signal in plain English (what dislocated and how)\n"
        "- **Catalyst & timing:** the likely driver and when reversion/fade should play out\n"
        "- **Risks:** what would invalidate the trade\n"
        "- **Conviction:** High, Med, or Low\n\n"
        "Rules: A candidate whose triage verdict is MECHANICAL_DISLOCATION is a "
        "tradeable LONG/SHORT (per its side). A candidate whose triage verdict is "
        "BROKEN_STORY or NEEDS_DATA must be marked PASS with an explicit short "
        "REJECT rationale (1 sentence) explaining why. Ground EVERYTHING only in "
        "the rows and triage notes provided — do NOT invent tickers, prices, or "
        "fundamentals. Use markdown headers.\n\n"
        f"## Long candidates (oversold-reversion)\n{long_lines}\n\n"
        f"## Short candidates (overbought-fade)\n{short_lines}\n"
    )


def _parse_verdict(text: str) -> str:
    """Extract the VERDICT label from triage text. Defaults to NEEDS_DATA."""
    valid = {"MECHANICAL_DISLOCATION", "BROKEN_STORY", "NEEDS_DATA"}
    for line in (text or "").splitlines():
        s = line.strip()
        if s.upper().startswith("VERDICT:"):
            label = s.split(":", 1)[1].strip().upper()
            # tolerate trailing punctuation / markdown
            for v in valid:
                if v in label:
                    return v
    # fallback: scan whole text for any label token
    up = (text or "").upper()
    for v in ("MECHANICAL_DISLOCATION", "BROKEN_STORY", "NEEDS_DATA"):
        if v in up:
            return v
    return "NEEDS_DATA"


def _candidate_summary(sel: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Flat serializable list of selected candidates for persistence / display."""
    out: List[Dict[str, Any]] = []
    for side, rows in (("long", sel.get("longs", [])), ("short", sel.get("shorts", []))):
        for r in rows:
            out.append({
                "ticker": r.get("ticker"),
                "name": r.get("name"),
                "side": side,
                "sector": r.get("sector"),
                "sub_industry": r.get("sub_industry"),
                "rank_z": r.get("rank_z"),
                "peer_relative_z": r.get("peer_relative_z"),
                "rsi": r.get("rsi"),
                "reversion_score": r.get("reversion_score"),
                "fade_score": r.get("fade_score"),
                "dislocation_type": r.get("dislocation_type"),
            })
    return out


def generate_note(
    provider: Optional[LLMProvider],
    master: List[Dict[str, Any]],
    oversold: List[Dict[str, Any]],
    overbought: List[Dict[str, Any]],
    params: Optional[Dict[str, Any]] = None,
    max_longs: int = 2,
    max_shorts: int = 2,
    idio_only: bool = True,
    with_news: bool = False,
    asof: Any = None,
    fallback_providers: Optional[List[LLMProvider]] = None,
    web_provider: Optional[LLMProvider] = None,
) -> Dict[str, Any]:
    """Orchestrate select -> per-name catalyst triage -> note synthesis.

    Returns {"markdown", "candidates", "asof", "provider", "error", "notice"}.
    With provider=None / unavailable returns the candidate selection with
    markdown="" and a clear "set a key" error — NEVER raises.

    SPLIT PROVIDER (mirrors the weekly note): the NOTE SYNTHESIS always runs on
    the main ``provider`` (the chosen strong model — Anthropic/DeepSeek). The
    per-name CATALYST TRIAGE routes to ``web_provider`` when it is supplied AND
    web-capable (Perplexity); otherwise it falls back to the main ``provider``
    ONLY when that is itself web-capable; otherwise no web runs (deterministic /
    event-only tagging + a soft notice). This lets the user pick Claude/DeepSeek
    for synthesis while catalysts still fire via Perplexity when a key is set.

    ``with_news`` enables web-grounded catalyst lookup (Option A): the per-name
    triage prompt instructs a web-capable provider (Perplexity) to find WHY a
    ticker moved instead of defaulting to NEEDS_DATA. It defaults on when EITHER
    ``provider`` or ``web_provider`` is web-capable. If with_news is requested
    but NEITHER is web-capable, a soft ``notice`` is returned (no crash).

    Deterministic event tagging (Option C): any candidate row whose
    ``event_flag`` is truthy is pre-tagged MECHANICAL_DISLOCATION (source=event)
    without needing the LLM. With web lookup on we still run the LLM for color,
    but an event-flagged name that the LLM calls NEEDS_DATA is overridden back to
    MECHANICAL_DISLOCATION (event-backed) rather than PASS.
    """
    sel = select_candidates(
        master, oversold, overbought,
        max_longs=max_longs, max_shorts=max_shorts, idio_only=idio_only,
    )
    candidates = _candidate_summary(sel)

    if provider is None or not getattr(provider, "available", False):
        return {
            "markdown": "",
            "candidates": candidates,
            "asof": asof,
            "provider": None,
            "error": "Set an AI key in Settings to generate the research note.",
            "notice": "",
        }

    fallback_providers = fallback_providers or []

    # SPLIT PROVIDER routing. The triage step prefers a dedicated web-capable
    # ``web_provider`` (Perplexity); else it uses the main ``provider`` only when
    # that is itself web-capable; else there is no web runner and triage is
    # deterministic/event-only. The synthesis step below ALWAYS uses ``provider``.
    def _avail(p: Optional[LLMProvider]) -> bool:
        return p is not None and bool(getattr(p, "available", False))

    web_provider_capable = _avail(web_provider) and is_web_capable(web_provider)
    provider_web_capable = is_web_capable(provider)
    if web_provider_capable:
        web_runner: Optional[LLMProvider] = web_provider
    elif provider_web_capable:
        web_runner = provider
    else:
        web_runner = None
    # ``web_capable`` reflects whether the triage step can actually ground in web
    # search for THIS run (either provider carried the web capability).
    web_capable = web_runner is not None

    notice = ""
    if with_news and not web_capable:
        synth_name = getattr(provider, "name", "") or "the chosen model"
        notice = (
            "Live catalyst lookup needs a Perplexity key; add one to enable web "
            f"catalysts (synthesis ran on {synth_name})."
        )
    # Fallbacks are only meaningful when the web runner IS the main provider; a
    # dedicated Perplexity web provider should retry on itself, not on the
    # synthesis fallbacks (mirrors the weekly note).
    triage_fallbacks = fallback_providers if web_runner is provider else []

    errors: List[str] = []
    triaged: Dict[str, List[Dict[str, Any]]] = {"longs": [], "shorts": []}
    for side, key in (("long", "longs"), ("short", "shorts")):
        for r in sel[key]:
            has_event = bool(r.get("event_flag"))
            event_date = r.get("event_date")
            verdict, rationale, source = "NEEDS_DATA", "", "llm"

            # Deterministic pre-tag: a known corporate event in-window is a
            # mechanical/technical dislocation by construction.
            if has_event:
                verdict = "MECHANICAL_DISLOCATION"
                source = "event"
                rationale = (
                    f"Auto-tagged: corporate event on {event_date or '(date n/a)'} "
                    "within window — mechanical/technical dislocation likely."
                )

            # The triage runner is the split web runner when one exists
            # (Perplexity or a web-capable synthesis provider), else the main
            # provider for deterministic (non-web) classification of non-event
            # names. Web grounding only actually happens when ``web_capable``.
            triage_runner = web_runner if web_runner is not None else provider
            triage_with_news = bool(with_news) and web_capable

            # Run the LLM when it can add value: either there's no event pre-tag,
            # or web lookup is on (web context can refine WHICH event / add color).
            run_llm = (not has_event) or (with_news and web_capable)
            if run_llm and triage_runner is not None:
                try:
                    # Triage: retry on the SAME runner first (web behavior
                    # depends on Perplexity); only fall back if it stays
                    # overloaded — a non-web fallback answer is acceptable.
                    text, _used = complete_with_fallback(
                        triage_runner,
                        build_catalyst_prompt(r, side, with_news=triage_with_news),
                        fallback_providers=triage_fallbacks,
                        section="triage",
                        max_tokens=300,
                    )
                    llm_verdict = _parse_verdict(text)
                    llm_rationale = (text or "").strip()
                    if has_event:
                        # Event flag biases toward mechanical: never let the LLM
                        # downgrade an event-backed name to NEEDS_DATA/PASS.
                        if llm_verdict == "NEEDS_DATA":
                            verdict = "MECHANICAL_DISLOCATION"
                        else:
                            verdict = llm_verdict
                        source = "event+llm"
                        rationale = llm_rationale or rationale
                    else:
                        verdict = llm_verdict
                        rationale = llm_rationale
                        source = "llm"
                        # Option B: a name with NO universe event_flag, rescued
                        # by what the WEB found. If web lookup actually ran for
                        # this triage and the cautious model returned NEEDS_DATA
                        # while its rationale describes a concrete mechanical
                        # event, upgrade to MECHANICAL_DISLOCATION. BROKEN_STORY
                        # is a real reject and is never upgraded.
                        if (
                            with_news and web_capable
                            and llm_verdict == "NEEDS_DATA"
                        ):
                            matched = detect_mechanical_event(llm_rationale)
                            if matched:
                                verdict = "MECHANICAL_DISLOCATION"
                                source = "web-event"
                                rationale = (
                                    f"Web-detected mechanical event ({matched}); "
                                    "upgraded from NEEDS_DATA. "
                                    + (llm_rationale or "")
                                ).strip()
                    _log_usage(triage_runner, "sidebar", ok=True, note=f"triage {r.get('ticker')}")
                except Exception as e:  # noqa: BLE001
                    errors.append(f"triage {r.get('ticker')}: {e}")
                    _log_usage(triage_runner, "sidebar", ok=False, note=str(e)[:200])
                    # On error the deterministic event pre-tag (if any) stands.

            triaged[key].append({
                "row": r, "side": side, "verdict": verdict,
                "rationale": rationale, "source": source, "event_date": event_date,
            })

    markdown = ""
    try:
        prompt = build_note_prompt(triaged, asof)
        if with_news:
            prompt += (
                "\n\nIf you have access to live recent-news context, use it to "
                "validate or update the catalyst for each name; otherwise rely "
                "strictly on the rows above and do not fabricate news.\n"
            )
        text, _used = complete_with_fallback(
            provider, prompt,
            fallback_providers=fallback_providers,
            section="note", max_tokens=1200,
        )
        markdown = text or ""
        _log_usage(provider, "sidebar", ok=True, note="note synthesis")
    except Exception as e:  # noqa: BLE001
        errors.append(f"note: {e}")
        _log_usage(provider, "sidebar", ok=False, note=str(e)[:200])

    # Attach triage verdict + provenance to the candidate summary for
    # display/persistence (candidates_json is free-form; no schema change).
    by_ticker = {}
    for key in ("longs", "shorts"):
        for c in triaged[key]:
            by_ticker[(c["side"], c["row"].get("ticker"))] = c
    for c in candidates:
        t = by_ticker.get((c["side"], c["ticker"]))
        if t:
            c["verdict"] = t["verdict"]
            c["source"] = t.get("source")
            c["event_date"] = t.get("event_date")
        else:
            c["verdict"] = None

    return {
        "markdown": markdown,
        "candidates": candidates,
        "asof": asof,
        "provider": getattr(provider, "name", ""),
        "error": "; ".join(errors) if errors else "",
        "notice": notice,
    }
