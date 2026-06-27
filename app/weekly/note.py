"""Phase D weekly one-pager drafting — LLM, key-gated, resilient.

Assembles a single-page weekly note from the PURE metrics produced by
``metrics.compute_weekly_metrics``:

  (a) DATA OBSERVATIONS — prose grounded ONLY in the computed movers /
      opportunities tables (no fabrication).
  (b) WEB CATALYSTS — for the top5 gainers + bottom5 losers (+ any outsized
      intra-week volume spike), look up the likely reason for the move. Routes
      to a dedicated ``web_provider`` (Perplexity) when supplied, independent of
      the synthesis provider; falls back to ``provider`` only if it is itself
      web-capable; otherwise skipped with a soft notice.
  (c) HSI MACRO VIEW — the index's own weekly + YTD move (computed) plus a
      top-down commentary, web-augmented for macro/policy/flow context.

Mirrors app/llm/research_notes.py conventions exactly: best-effort usage
logging, ``is_web_capable`` gating, ``complete_with_fallback`` for retry +
provider fallback, and a structured return that NEVER raises. With no provider
(or an unavailable one) the note degrades to the raw D4 metric tables rendered
as markdown plus a "set a key" hint — still a usable deliverable.

The returned dict is shaped to feed exporters.export directly:

    {
      "markdown": <assembled one-pager>,
      "candidates": [],            # weekly note has no candidate table
      "asof": <as-of>,
      "provider": <name|None>,
      "error": <str>, "notice": <str>,
      "title": "Weekly Quant One-Pager",
      "kind": "weekly",
    }
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..llm.base import LLMProvider
from ..llm.research_notes import _log_usage, is_web_capable
from ..llm.resilience import complete_with_fallback

TITLE = "Weekly Quant One-Pager"


# ---------------------------------------------------------------------------
# Formatting helpers (pure, NaN/None-safe)
# ---------------------------------------------------------------------------
def _pct(v: Any) -> str:
    try:
        if v is None:
            return "—"
        return f"{float(v) * 100:+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _ratio(v: Any) -> str:
    try:
        if v is None:
            return "—"
        return f"{float(v):.2f}x"
    except (TypeError, ValueError):
        return "—"


def _num(v: Any, spec: str = ".2f") -> str:
    try:
        if v is None:
            return "—"
        return format(float(v), spec)
    except (TypeError, ValueError):
        return "—"


def _vol(v: Any) -> str:
    """Annualized vol as a percent (it is already a fraction)."""
    try:
        if v is None:
            return "—"
        return f"{float(v) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    if not rows:
        return "_None._\n"
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Deterministic metric -> markdown tables (the data backbone; always rendered)
# ---------------------------------------------------------------------------
def _attr_phrase(attr: Dict[str, Any]) -> str:
    """One-line attribution descriptor: tag + peer median + residual (pp)."""
    attr = attr or {}
    tag = attr.get("attribution")
    if not tag:
        return "—"
    pm = attr.get("peer_median_1w")
    res = attr.get("residual_1w")
    grp = attr.get("peer_group_used")
    n = attr.get("peer_count")
    bits = [str(tag)]
    if pm is not None:
        bits.append(f"peer med {_pct(pm)}")
    if res is not None:
        bits.append(f"resid {_pct(res)}")
    if grp and n:
        bits.append(f"{grp} n={n}")
    return "; ".join(bits)


def render_fundamentals_table(metrics: Dict[str, Any]) -> str:
    """Compact 'Fundamentals & attribution' table for the notable movers.

    Rendered ONLY when at least one notable mover carries fundamentals or an
    attribution tag; otherwise returns ''. Strictly reflects computed values,
    n/a (—) where missing. Never raises."""
    metrics = metrics or {}
    per = metrics.get("per_ticker") or {}
    names = metrics.get("catalyst_names") or []
    rows: List[List[str]] = []
    any_data = False
    for sym in names:
        m = per.get(sym, {}) or {}
        mom = m.get("momentum") or {}
        attr = m.get("attribution") or {}
        if m.get("has_fundamentals") or attr.get("attribution"):
            any_data = True
        rev_dir = mom.get("revision_dir") or "—"
        rows.append([
            str(sym),
            _pct(m.get("ret_1w")),
            _ratio(m.get("fwd_pe")),
            (f"{rev_dir} {_pct(mom.get('revision_pct'))}"
             if mom.get("revision_pct") is not None else rev_dir),
            _pct(mom.get("dispersion")),
            (str(m.get("sector")) if m.get("sector") else "—"),
            _attr_phrase(attr),
        ])
    if not any_data:
        return ""
    return (
        "\n### Fundamentals & attribution (notable movers)\n"
        + _md_table(
            ["Symbol", "1W", "Fwd P/E", "EPS rev (4wk)", "Disp",
             "Sector", "Attribution"],
            rows,
        )
        + "_Fwd P/E = latest close / FY1 EPS mean (— when EPS≤0/missing). "
        "EPS rev = 4-week change in FY1 EPS mean. Disp = stddev/|FY1 EPS|. "
        "Attribution nets the 1W move vs a leave-one-out peer median._\n"
    )


def render_metric_tables(metrics: Dict[str, Any]) -> str:
    """The pure, deterministic D4 view as markdown. Used both as grounding for
    the LLM and as the no-key fallback body. Never raises."""
    metrics = metrics or {}
    movers = metrics.get("movers") or {}
    opps = metrics.get("opportunities") or {}
    hsi = metrics.get("hsi") or {}
    parts: List[str] = []

    # Movers & shakers
    parts.append("### Movers & shakers\n")
    parts.append("**Top gainers (1W)**\n")
    parts.append(_md_table(
        ["Symbol", "1W", "vs HSI", "Vol x"],
        [[str(r.get("symbol")), _pct(r.get("ret_1w")), _pct(r.get("rel_1w")),
          _ratio(r.get("vol_ratio"))] for r in movers.get("gainers_1w", [])],
    ))
    parts.append("\n**Top losers (1W)**\n")
    parts.append(_md_table(
        ["Symbol", "1W", "vs HSI", "Vol x"],
        [[str(r.get("symbol")), _pct(r.get("ret_1w")), _pct(r.get("rel_1w")),
          _ratio(r.get("vol_ratio"))] for r in movers.get("losers_1w", [])],
    ))
    parts.append("\n**Biggest volume shifts (week avg vs 20D ADV)**\n")
    parts.append(_md_table(
        ["Symbol", "Vol x", "Spike x", "1W"],
        [[str(r.get("symbol")), _ratio(r.get("vol_ratio")),
          _ratio(r.get("max_spike_ratio")), _pct(r.get("ret_1w"))]
         for r in movers.get("vol_shift", [])],
    ))
    parts.append("\n**Highest volatility (20D annualized)**\n")
    parts.append(_md_table(
        ["Symbol", "20D vol", "60D vol", "Elevated"],
        [[str(r.get("symbol")), _vol(r.get("vol_20d")), _vol(r.get("vol_60d")),
          ("yes" if r.get("vol_elevated") else "no")]
         for r in movers.get("vola_shift", [])],
    ))
    parts.append("\n**HSI-relative leaders / laggards (1W)**\n")
    lead = movers.get("rel_leaders", [])
    lag = movers.get("rel_laggards", [])
    parts.append(_md_table(
        ["Symbol", "vs HSI 1W", "1W"],
        [[str(r.get("symbol")), _pct(r.get("rel_1w")), _pct(r.get("ret_1w"))]
         for r in (lead + lag)],
    ))

    # Opportunities / gaps
    parts.append("\n### Opportunities & gaps\n")
    parts.append("**Dislocations (large 1W move + high z vs own history)**\n")
    parts.append(_md_table(
        ["Symbol", "1W", "z", "vs HSI"],
        [[str(r.get("symbol")), _pct(r.get("ret_1w")), _num(r.get("z_1w")),
          _pct(r.get("rel_1w"))] for r in opps.get("dislocations", [])],
    ))
    parts.append("\n**Relative-value (lagging HSI YTD, low vol / improving momentum)**\n")
    parts.append(_md_table(
        ["Symbol", "vs HSI YTD", "20D vol", "1M mom"],
        [[str(r.get("symbol")), _pct(r.get("rel_ytd")), _vol(r.get("vol_20d")),
          _pct(r.get("mom_1m"))] for r in opps.get("relative_value", [])],
    ))
    parts.append("\n**Anomalies (volume spike w/o price move; vol regime break)**\n")
    parts.append(_md_table(
        ["Symbol", "Kind", "Spike x", "1W"],
        [[str(r.get("symbol")), str(r.get("kind") or ""),
          _ratio(r.get("max_spike_ratio")), _pct(r.get("ret_1w"))]
         for r in opps.get("anomalies", [])],
    ))

    # HSI macro snapshot (computed)
    parts.append("\n### HSI benchmark (computed)\n")
    parts.append(_md_table(
        ["Window", "Return"],
        [["1W", _pct(hsi.get("ret_1w"))], ["1M", _pct(hsi.get("ret_1m"))],
         ["3M", _pct(hsi.get("ret_3m"))], ["YTD", _pct(hsi.get("ret_ytd"))],
         ["20D vol (ann.)", _vol(hsi.get("vol_20d"))],
         ["Short trend", str(hsi.get("trend") or "n/a")]],
    ))

    # Fundamentals & attribution (only when present for notable movers).
    fund_tbl = render_fundamentals_table(metrics)
    if fund_tbl:
        parts.append(fund_tbl)
    return "\n".join(parts)


def _staleness_banner(metrics: Dict[str, Any]) -> str:
    asof = metrics.get("asof") or "unknown"
    n_stale = metrics.get("n_stale")
    if metrics.get("stale"):
        return (f"_As of {asof}_ — ⚠ data is {n_stale} business days old; "
                "refresh the FactSet pull for a current read.")
    return f"_As of {asof}_"


# ---------------------------------------------------------------------------
# Prompt builders (pure)
# ---------------------------------------------------------------------------
def build_observations_prompt(metrics: Dict[str, Any]) -> str:
    asof = metrics.get("asof") or "the as-of date"
    tables = render_metric_tables(metrics)
    return (
        "You are an equity strategist writing the DATA-DRIVEN section of a weekly "
        f"one-pager for a Hang Seng (HSI) universe, as of {asof}.\n\n"
        "Below are metric tables computed IN-APP from raw FactSet price/volume "
        "series (returns are simple % price change; relative = stock minus HSI; "
        "volatility is annualized stdev of daily returns; momentum is trailing "
        "return and 3M-return/20D-vol). Write 2-4 tight paragraphs of prose that "
        "summarize the week's movers & shakers and the most interesting "
        "opportunities/gaps. Where the Fundamentals & attribution table is "
        "present, weave in the relevant forward P/E, 4-week EPS revision "
        "direction/magnitude, estimate dispersion, and — critically — whether each "
        "notable move was Stock-specific, Sector-driven, or Mixed (per the "
        "leave-one-out peer-median attribution). Ground EVERYTHING strictly in "
        "these numbers — do NOT invent tickers, prices, news, or catalysts (a "
        "separate section covers catalysts), and write n/a where a fundamental is "
        "missing. Be concise and specific; cite the figures. Use plain prose, "
        "no headers.\n\n"
        f"{tables}\n"
    )


def build_catalyst_prompt(metrics: Dict[str, Any]) -> str:
    asof = metrics.get("asof") or "the as-of date"
    names = metrics.get("catalyst_names") or []
    per = metrics.get("per_ticker") or {}
    lines: List[str] = []
    for sym in names:
        m = per.get(sym, {})
        mom = m.get("momentum") or {}
        attr = m.get("attribution") or {}
        extra = ""
        # Fundamentals context (only when present).
        fparts: List[str] = []
        if m.get("fwd_pe") is not None:
            fparts.append(f"fwd P/E {_ratio(m.get('fwd_pe'))}")
        if mom.get("revision_dir"):
            fparts.append(
                f"FY1 EPS revised {mom.get('revision_dir')} "
                f"{_pct(mom.get('revision_pct'))} over 4wks"
            )
        if fparts:
            extra += " Fundamentals: " + ", ".join(fparts) + "."
        # Attribution-steered guidance for the web lookup.
        tag = attr.get("attribution")
        if tag == "Stock-specific":
            extra += (
                " Attribution: STOCK-SPECIFIC (residual "
                f"{_pct(attr.get('residual_1w'))} vs peer median "
                f"{_pct(attr.get('peer_median_1w'))}) — prioritize NAME-LEVEL "
                "catalysts (this company's earnings/guidance, M&A, contracts, "
                "management, single-stock news)."
            )
        elif tag == "Sector-driven":
            extra += (
                " Attribution: SECTOR-DRIVEN (peer median "
                f"{_pct(attr.get('peer_median_1w'))}, small residual "
                f"{_pct(attr.get('residual_1w'))}) — prioritize the SECTOR / MACRO "
                "driver (policy, commodity/rate moves, sector rotation/flows) "
                "rather than name-specific news."
            )
        elif tag == "Mixed":
            extra += (
                " Attribution: MIXED — check BOTH a sector/macro driver and any "
                "name-specific catalyst."
            )
        lines.append(
            f"- {sym}: 1W {_pct(m.get('ret_1w'))}, vs HSI {_pct(m.get('rel_1w'))}, "
            f"volume {_ratio(m.get('vol_ratio'))} of 20D ADV, "
            f"max single-day spike {_ratio(m.get('max_spike_ratio'))}.{extra}"
        )
    namelist = "\n".join(lines) or "(none)"
    return (
        "You are an equity strategist. Use LIVE WEB / RECENT-NEWS search to find "
        "the LIKELY catalyst behind each notable move below in a Hang Seng (HSI) "
        f"universe over the week ending {asof}. Let the ATTRIBUTION tag on each "
        "name STEER your search: Stock-specific → hunt company-level catalysts; "
        "Sector-driven → identify the sector/macro driver; Mixed → cover both. "
        "For each name, look for: earnings "
        "or guidance, M&A, regulatory/policy news, sector flows, index "
        "inclusion/exclusion or rebalance, ex-dividend/forced flow. Write ONE "
        "short bullet per name: the symbol, the 1W move, and the cited catalyst "
        "(one sentence). If web search yields nothing specific for a name, say "
        "'no specific catalyst found' for it — do NOT fabricate. Keep it tight.\n\n"
        f"Notable movers (top gainers, top losers, outsized volume):\n{namelist}\n"
    )


def build_hsi_prompt(metrics: Dict[str, Any]) -> str:
    asof = metrics.get("asof") or "the as-of date"
    hsi = metrics.get("hsi") or {}
    computed = (
        f"Computed HSI move: 1W {_pct(hsi.get('ret_1w'))}, 1M {_pct(hsi.get('ret_1m'))}, "
        f"3M {_pct(hsi.get('ret_3m'))}, YTD {_pct(hsi.get('ret_ytd'))}, "
        f"20D annualized vol {_vol(hsi.get('vol_20d'))}, short trend "
        f"{hsi.get('trend') or 'n/a'}."
    )
    return (
        "You are a macro strategist writing the TOP-DOWN index section of a weekly "
        f"one-pager on the Hang Seng Index (HSI), as of {asof}. Start from the "
        f"computed figures below, then add a brief (1-2 paragraph) interpretation "
        "of the index week. If you have live web context, fold in the macro / "
        "policy / flow drivers (China data, PBoC/HKMA, Stock Connect flows, "
        "sector rotation); otherwise interpret strictly from the computed move and "
        "do not fabricate news. Use plain prose, no headers.\n\n"
        f"{computed}\n"
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _no_key_markdown(metrics: Dict[str, Any]) -> str:
    banner = _staleness_banner(metrics)
    tables = render_metric_tables(metrics)
    return (
        f"# {TITLE}\n\n{banner}\n\n"
        "> Set an AI key in Settings to generate the written weekly note. The "
        "computed metrics below are the data backbone and are always available.\n\n"
        f"{tables}\n"
    )


def _assemble(
    metrics: Dict[str, Any],
    observations: str,
    catalysts: str,
    hsi_commentary: str,
    notice: str,
) -> str:
    banner = _staleness_banner(metrics)
    parts: List[str] = [f"# {TITLE}", "", banner, ""]
    if notice:
        parts += [f"> {notice}", ""]
    if observations.strip():
        parts += ["## Data observations", "", observations.strip(), ""]
    if catalysts.strip():
        parts += ["## Catalysts (web)", "", catalysts.strip(), ""]
    if hsi_commentary.strip():
        parts += ["## HSI macro view", "", hsi_commentary.strip(), ""]
    # Always append the deterministic data tables for auditability.
    parts += ["## Computed metrics", "", render_metric_tables(metrics)]
    return "\n".join(parts)



def generate_weekly_note(
    provider: Optional[LLMProvider],
    metrics: Dict[str, Any],
    asof: Any = None,
    with_news: Optional[bool] = False,
    fallback_providers: Optional[List[LLMProvider]] = None,
    web_provider: Optional[LLMProvider] = None,
) -> Dict[str, Any]:
    """Assemble the weekly one-pager with a SPLIT provider model. NEVER raises.

    Two distinct duties:
      * SYNTHESIS (data-driven observations prose + HSI macro narrative) runs on
        ``provider`` -- the user's chosen model (Claude / DeepSeek / Perplexity).
      * WEB lookups (per-mover catalysts + HSI macro web/context) route to
        ``web_provider`` when it is supplied AND web-capable; otherwise they
        fall back to ``provider`` IF that is itself web-capable; otherwise web
        is skipped and a soft notice is set.

    ``with_news`` gating: False -> skip web entirely. None -> default to True
    when EITHER ``provider`` or ``web_provider`` is web-capable. True -> attempt
    web (subject to a web-capable provider existing).

    Degradation: with both ``provider`` and ``web_provider`` None/unavailable
    the note is the raw metric tables + a "set a key" hint. With only
    ``web_provider`` available (no synthesis key) the quant tables + web
    catalysts are still produced. Usage is logged best-effort for whichever
    provider actually answered each section.
    """
    metrics = metrics or {}
    if asof is None:
        asof = metrics.get("asof")

    base = {
        "candidates": [],
        "asof": asof,
        "title": TITLE,
        "kind": "weekly",
    }

    def _avail(p: Optional[LLMProvider]) -> bool:
        return p is not None and bool(getattr(p, "available", False))

    synth_ok = _avail(provider)
    web_prov_ok = _avail(web_provider)

    # No usable provider at all -> degrade to the deterministic tables + hint.
    if not synth_ok and not web_prov_ok:
        return {
            **base,
            "markdown": _no_key_markdown(metrics),
            "provider": None,
            "error": "Set an AI key in Settings to generate the weekly note.",
            "notice": "",
        }

    fallback_providers = fallback_providers or []
    synth_web_capable = synth_ok and is_web_capable(provider)
    web_capable_web_provider = web_prov_ok and is_web_capable(web_provider)

    # Resolve which provider (if any) services the WEB sections.
    if web_capable_web_provider:
        web_runner: Optional[LLMProvider] = web_provider
    elif synth_web_capable:
        web_runner = provider
    else:
        web_runner = None

    # with_news gating.
    if with_news is None:
        with_news = synth_web_capable or web_capable_web_provider
    do_web = bool(with_news) and web_runner is not None

    notice = ""
    if with_news and web_runner is None:
        synth_name = getattr(provider, "name", "") or "the chosen model"
        notice = (
            "Live web catalysts need a Perplexity key; synthesis ran on "
            f"{synth_name}."
        )

    errors: List[str] = []

    # (a) Data observations [SYNTHESIS] -- run on the chosen provider.
    observations = ""
    if synth_ok:
        try:
            text, _used = complete_with_fallback(
                provider, build_observations_prompt(metrics),
                fallback_providers=fallback_providers,
                section="weekly_obs", max_tokens=900,
            )
            observations = (text or "").strip()
            _log_usage(provider, "sidebar", ok=True, note="weekly observations")
        except Exception as e:  # noqa: BLE001
            errors.append(f"observations: {e}")
            _log_usage(provider, "sidebar", ok=False, note=str(e)[:200])

    # (b) Web catalysts [WEB] -- route to the resolved web runner.
    catalysts = ""
    if do_web and (metrics.get("catalyst_names") or []):
        try:
            text, _used = complete_with_fallback(
                web_runner, build_catalyst_prompt(metrics),
                fallback_providers=[],
                section="weekly_catalysts", max_tokens=800,
            )
            catalysts = (text or "").strip()
            _log_usage(web_runner, "sidebar", ok=True, note="weekly catalysts")
        except Exception as e:  # noqa: BLE001
            errors.append(f"catalysts: {e}")
            _log_usage(web_runner, "sidebar", ok=False, note=str(e)[:200])

    # (c) HSI macro view -- NARRATIVE is synthesis; web/context is the web step.
    # When a synthesis provider exists, the prose is authored by it (web-aware
    # only if it is itself the web runner). When only a web provider exists, the
    # web runner authors it so we still get a macro read.
    hsi_commentary = ""
    hsi_runner = provider if synth_ok else web_runner
    if hsi_runner is not None and (metrics.get("hsi") or {}).get("loaded"):
        try:
            text, _used = complete_with_fallback(
                hsi_runner, build_hsi_prompt(metrics),
                fallback_providers=(fallback_providers if hsi_runner is provider else []),
                section="weekly_hsi", max_tokens=600,
            )
            hsi_commentary = (text or "").strip()
            _log_usage(hsi_runner, "sidebar", ok=True, note="weekly hsi")
        except Exception as e:  # noqa: BLE001
            errors.append(f"hsi: {e}")
            _log_usage(hsi_runner, "sidebar", ok=False, note=str(e)[:200])

    markdown = _assemble(metrics, observations, catalysts, hsi_commentary, notice)

    # Report the synthesis provider name when present, else the web provider.
    prov_name = (getattr(provider, "name", "") if synth_ok
                 else getattr(web_provider, "name", ""))

    return {
        **base,
        "markdown": markdown,
        "provider": prov_name,
        "error": "; ".join(errors) if errors else "",
        "notice": notice,
    }
