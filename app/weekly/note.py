"""Phase D weekly one-pager drafting — LLM, key-gated, resilient.

Assembles a single-page weekly note from the PURE metrics produced by
``metrics.compute_weekly_metrics``:

  (a) DATA OBSERVATIONS — prose grounded ONLY in the computed movers /
      opportunities tables (no fabrication).
  (b) WEB CATALYSTS — for the top5 gainers + bottom5 losers (+ any outsized
      intra-week volume spike), look up the likely reason for the move. Only
      fires with a web-capable provider (Perplexity); otherwise a soft notice.
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
        "opportunities/gaps. Ground EVERYTHING strictly in these numbers — do NOT "
        "invent tickers, prices, news, or catalysts (a separate section covers "
        "catalysts). Be concise and specific; cite the figures. Use plain prose, "
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
        lines.append(
            f"- {sym}: 1W {_pct(m.get('ret_1w'))}, vs HSI {_pct(m.get('rel_1w'))}, "
            f"volume {_ratio(m.get('vol_ratio'))} of 20D ADV, "
            f"max single-day spike {_ratio(m.get('max_spike_ratio'))}."
        )
    namelist = "\n".join(lines) or "(none)"
    return (
        "You are an equity strategist. Use LIVE WEB / RECENT-NEWS search to find "
        "the LIKELY catalyst behind each notable move below in a Hang Seng (HSI) "
        f"universe over the week ending {asof}. For each name, look for: earnings "
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
    with_news: bool = False,
    fallback_providers: Optional[List[LLMProvider]] = None,
) -> Dict[str, Any]:
    """Assemble the weekly one-pager. NEVER raises.

    With provider=None / unavailable: returns the raw metric tables as markdown
    plus a "set a key" hint (still a usable note). With a non-web-capable
    provider and ``with_news`` requested: the catalyst section is skipped with a
    soft notice. Usage is logged best-effort.
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

    if provider is None or not getattr(provider, "available", False):
        return {
            **base,
            "markdown": _no_key_markdown(metrics),
            "provider": None,
            "error": "Set an AI key in Settings to generate the weekly note.",
            "notice": "",
        }

    fallback_providers = fallback_providers or []
    web_capable = is_web_capable(provider)
    notice = ""
    if with_news and not web_capable:
        notice = ("Live catalyst lookup needs a Perplexity provider; current "
                  "provider has no web access — showing the quant note without "
                  "web catalysts.")

    errors: List[str] = []

    # (a) Data observations — always run (grounded in computed metrics).
    observations = ""
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

    # (b) Web catalysts — only when web-capable AND requested.
    catalysts = ""
    if with_news and web_capable and (metrics.get("catalyst_names") or []):
        try:
            text, _used = complete_with_fallback(
                provider, build_catalyst_prompt(metrics),
                fallback_providers=fallback_providers,
                section="weekly_catalysts", max_tokens=800,
            )
            catalysts = (text or "").strip()
            _log_usage(provider, "sidebar", ok=True, note="weekly catalysts")
        except Exception as e:  # noqa: BLE001
            errors.append(f"catalysts: {e}")
            _log_usage(provider, "sidebar", ok=False, note=str(e)[:200])

    # (c) HSI macro view — run when HSI series is present.
    hsi_commentary = ""
    if (metrics.get("hsi") or {}).get("loaded"):
        try:
            text, _used = complete_with_fallback(
                provider, build_hsi_prompt(metrics),
                fallback_providers=fallback_providers,
                section="weekly_hsi", max_tokens=600,
            )
            hsi_commentary = (text or "").strip()
            _log_usage(provider, "sidebar", ok=True, note="weekly hsi")
        except Exception as e:  # noqa: BLE001
            errors.append(f"hsi: {e}")
            _log_usage(provider, "sidebar", ok=False, note=str(e)[:200])

    markdown = _assemble(metrics, observations, catalysts, hsi_commentary, notice)

    return {
        **base,
        "markdown": markdown,
        "provider": getattr(provider, "name", ""),
        "error": "; ".join(errors) if errors else "",
        "notice": notice,
    }
