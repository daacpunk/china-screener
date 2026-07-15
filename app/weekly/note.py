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

import re
from typing import Any, Dict, List, Optional, Tuple

from . import metrics as wmetrics
from ..llm.base import LLMProvider
from ..llm.research_notes import _log_usage, is_web_capable
from ..llm.resilience import complete_with_fallback

TITLE = "Weekly Quant One-Pager"

# Characters that show up as FactSet text-pull rendering artifacts (■ etc.).
# We defensively strip them here too so a name never carries them into the note.
_ARTIFACT_RE = re.compile("[\u25a0\ufffd\ufeff\u0000-\u001f\u007f-\u009f]")


def _clean(s: Any) -> str:
    """Strip ■/non-printable artifacts and collapse whitespace from a label."""
    if s is None:
        return ""
    txt = _ARTIFACT_RE.sub(" ", str(s))
    txt = "".join(ch for ch in txt if ch.isprintable() or ch.isspace())
    return re.sub(r"\s+", " ", txt).strip()


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


def fmt_dollars(x: Any) -> str:
    """Compact human dollar formatting with a neutral "$" label (#4):
    $1.2b / $85m / $950k / $120. None / non-finite -> "\u2014".

    Uses one decimal place for the b/m/k scales (e.g. $1.2b, $85.0m -> $85m: a
    trailing ".0" is trimmed), and no decimals below 1,000. Pure, never raises."""
    try:
        if x is None:
            return "\u2014"
        v = float(x)
    except (TypeError, ValueError):
        return "\u2014"
    import math as _m
    if not _m.isfinite(v):
        return "\u2014"
    neg = v < 0
    a = abs(v)
    if a >= 1e9:
        s = f"{a / 1e9:.1f}b"
    elif a >= 1e6:
        s = f"{a / 1e6:.1f}m"
    elif a >= 1e3:
        s = f"{a / 1e3:.1f}k"
    else:
        s = f"{a:.0f}"
    # Trim a trailing ".0" on the scaled forms ($85.0m -> $85m).
    if s.endswith(("b", "m", "k")) and s[:-1].endswith(".0"):
        s = s[:-3] + s[-1]
    return f"-${s}" if neg else f"${s}"


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


# ---------------------------------------------------------------------------
# Readability helpers: company labels, sector tags, valuation anchors, plain
# English attribution + sigma. All pure / None-safe.
# ---------------------------------------------------------------------------
def _short_sector(rec: Dict[str, Any]) -> str:
    """A short sector tag for the descriptor (prefer the broad FactSet sector,
    fall back to the industry). '' when neither is present."""
    sec = _clean(rec.get("sector"))
    if sec:
        return sec
    return _clean(rec.get("industry") or rec.get("sub_industry"))


def _descriptor(rec: Dict[str, Any]) -> str:
    """Label a name as "Company Name (9636-HK)" using the cleaned company name
    with the ticker in parentheses. Degrades to the bare symbol when the company
    name is missing."""
    sym = _clean(rec.get("symbol")) or "?"
    name = _clean(rec.get("company_name"))
    return f"{name} ({sym})" if name else sym


def _val_anchor(rec: Dict[str, Any]) -> str:
    """Valuation anchor string: "11.8x vs sector ~9x (cheap)". '' when no fwd P/E.
    Shows the sector median + cheap/in line/rich descriptor when available."""
    pe = rec.get("fwd_pe")
    if pe is None:
        return ""
    try:
        base = f"{float(pe):.1f}x"
    except (TypeError, ValueError):
        return ""
    med = rec.get("sector_median_fwd_pe")
    vs = rec.get("valuation_vs_sector")
    if med is not None:
        try:
            base += f" vs sector ~{float(med):.0f}x"
        except (TypeError, ValueError):
            pass
    if vs:
        base += f" ({vs})"
    return base


def _sigma_str(rec: Dict[str, Any]) -> str:
    """The 1W-return sigma vs own history, e.g. '-5.7σ'. '' when unavailable."""
    z = rec.get("ret_sigma")
    if z is None:
        z = rec.get("z_1w")
    if z is None:
        return ""
    try:
        return f"{float(z):+.1f}σ"
    except (TypeError, ValueError):
        return ""


def _plain_attr(rec: Dict[str, Any]) -> str:
    """Translate the attribution dict into plain English: how much of the move
    was company-specific vs how the peers moved. '' when no attribution."""
    attr = rec.get("attribution") or {}
    tag = attr.get("attribution")
    if not tag:
        return ""
    pm = attr.get("peer_median_1w")
    if attr.get("peer_group_used") == "idiosyncratic-solo" or pm is None:
        if tag == "Stock-specific":
            return "no comparable peers, so treated as company-specific"
        return ""
    peer_txt = f"peers were about {_pct(pm)}"
    if tag == "Stock-specific":
        return f"{peer_txt}, so almost the entire move was company-specific"
    if tag == "Sector-driven":
        return f"moved with its sector ({peer_txt})"
    return f"a mix of sector ({peer_txt}) and company-specific factors"


def _mover_line(rec: Dict[str, Any]) -> str:
    """A single plain-English mover bullet: descriptor + 1W move + plain-English
    attribution + valuation anchor (when present). Deterministic; used as the
    no-key fallback AND as grounding lines fed to the AI."""
    head = f"{_descriptor(rec)} {_pct(rec.get('ret_1w'))}"
    parts = [head]
    pa = _plain_attr(rec)
    if pa:
        parts.append(f"— {pa}.")
    va = _val_anchor(rec)
    if va:
        vs = rec.get("valuation_vs_sector")
        if vs in ("cheap", "rich"):
            parts.append(f"Trades {vs} at {va.split(' (')[0]}.")
        else:
            parts.append(f"Forward P/E {va}.")
    rev_dir = rec.get("eps_revision_dir")
    rev_pct = rec.get("eps_revision_pct")
    if rev_dir in ("up", "down") and rev_pct is not None:
        verb = "raised" if rev_dir == "up" else "cut"
        parts.append(f"Analysts {verb} EPS estimates {_pct(rev_pct)} over 4 weeks.")
    return " ".join(parts)


def render_fundamentals_table(metrics: Dict[str, Any]) -> str:
    """Compact 'Fundamentals & attribution' table for the notable movers.

    Rendered ONLY when at least one notable mover carries fundamentals or an
    attribution tag; otherwise returns ''. Strictly reflects computed values,
    n/a (—) where missing. Never raises."""
    metrics = metrics or {}
    per = metrics.get("per_ticker") or {}
    names = metrics.get("catalyst_names") or []
    # DISPLAY order only: sort the rows by 1W return DESCENDING (largest gain
    # first, largest loss last) so the table reads top-down. This does NOT mutate
    # metrics["catalyst_names"] — other consumers (e.g. the catalyst web-lookup
    # loop) keep the original selection order. NaN-safe: any ticker with a
    # missing / None / non-finite ret_1w sorts to the very bottom, after every
    # valid one, and never crashes.
    def _ret1w_key(sym: str) -> float:
        m = per.get(sym, {}) or {}
        try:
            v = float(m.get("ret_1w"))
        except (TypeError, ValueError):
            return float("-inf")
        if v != v:  # NaN
            return float("-inf")
        return v
    names = sorted(names, key=_ret1w_key, reverse=True)
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
            fmt_dollars(m.get("advv_20d")),
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
            ["Symbol", "1W", "$ADV", "Fwd P/E", "EPS rev (4wk)", "Disp",
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
    asof = metrics.get("asof") or "unknown"
    parts: List[str] = []

    # As-of reminder for a reader who scrolls straight to the bottom tables.
    parts.append(f"_All figures below as of {asof}._\n")

    # Movers & shakers
    parts.append("### Movers & shakers\n")
    parts.append("**Top gainers (1W)**\n")
    parts.append(_md_table(
        ["Symbol", "1W", "vs HSI", "Vol x", "$ADV"],
        [[str(r.get("symbol")), _pct(r.get("ret_1w")), _pct(r.get("rel_1w")),
          _ratio(r.get("vol_ratio")), fmt_dollars(r.get("advv_20d"))]
         for r in movers.get("gainers_1w", [])],
    ))
    parts.append("\n**Top losers (1W)**\n")
    parts.append(_md_table(
        ["Symbol", "1W", "vs HSI", "Vol x", "$ADV"],
        [[str(r.get("symbol")), _pct(r.get("ret_1w")), _pct(r.get("rel_1w")),
          _ratio(r.get("vol_ratio")), fmt_dollars(r.get("advv_20d"))]
         for r in movers.get("losers_1w", [])],
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
        ["Symbol", "vs HSI 1W", "1W", "Beta", "Alpha (1W)"],
        [[str(r.get("symbol")), _pct(r.get("rel_1w")), _pct(r.get("ret_1w")),
          _num(r.get("beta_60d")), _pct(r.get("alpha_1w"))]
         for r in (lead + lag)],
    ))
    # Beta-adjusted alpha leaders / laggards (risk-adjusted vs own market
    # sensitivity). Rendered only when any alpha is available.
    a_lead = movers.get("alpha_leaders", [])
    a_lag = movers.get("alpha_laggards", [])
    if any(r.get("alpha_1w") is not None for r in (a_lead + a_lag)):
        parts.append("\n**Alpha leaders / laggards (1W, beta-adjusted vs HSI)**\n")
        parts.append(_md_table(
            ["Symbol", "Alpha (1W)", "1W", "Beta"],
            [[str(r.get("symbol")), _pct(r.get("alpha_1w")), _pct(r.get("ret_1w")),
              _num(r.get("beta_60d"))] for r in (a_lead + a_lag)],
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


# ---------------------------------------------------------------------------
# #1 Market internals + #6 Sector scoreboard rendering (pure, None-safe)
# ---------------------------------------------------------------------------
def _name_labels(metrics: Dict[str, Any], syms: List[str], cap: int = 6) -> str:
    """Render 'Company Name (TICKER)' labels for up to ``cap`` symbols, then a
    '+N more' tail. '' when the list is empty. None-safe."""
    per = metrics.get("per_ticker") or {}
    syms = list(syms or [])
    shown = syms[:cap]
    labels = []
    for s in shown:
        rec = per.get(s) or {"symbol": s}
        labels.append(_descriptor(rec))
    out = ", ".join(labels)
    extra = len(syms) - len(shown)
    if extra > 0:
        out += f" +{extra} more"
    return out


def render_market_internals(metrics: Dict[str, Any]) -> str:
    """The '## Market internals' section body (#1): A/D counts + breadth ratio,
    up/down dollar volume, new highs/lows, and a bolded divergence line when
    present. Returns '' when no breadth data is available (e.g. an old snapshot
    with no valid returns). Never raises."""
    b = metrics.get("breadth") or {}
    n_valid = b.get("n_valid") or 0
    regime_line = render_regime_line(metrics)
    if not n_valid:
        # No breadth data, but a regime read may still exist (>=5 names) — emit
        # just the regime line so the section is not lost.
        return f"- **{regime_line}**" if regime_line else ""
    adv = b.get("advancers") or 0
    dec = b.get("decliners") or 0
    flat = b.get("flat") or 0
    br = b.get("breadth_ratio")
    br_txt = (f"{float(br) * 100:.0f}%" if br is not None else "—")
    lines: List[str] = []
    lines.append(
        f"- **Advance / decline:** {adv} up, {dec} down, {flat} flat "
        f"of {n_valid} names \u2014 breadth ratio {br_txt}."
    )
    up_dv = b.get("up_dollar_vol")
    down_dv = b.get("down_dollar_vol")
    if up_dv is not None or down_dv is not None:
        lines.append(
            f"- **Up / down volume:** {fmt_dollars(up_dv)} traded in advancing "
            f"names vs {fmt_dollars(down_dv)} in declining names."
        )
    highs = b.get("new_highs") or []
    lows = b.get("new_lows") or []
    if highs:
        lines.append(f"- **New highs ({len(highs)}):** {_name_labels(metrics, highs)}.")
    if lows:
        lines.append(f"- **New lows ({len(lows)}):** {_name_labels(metrics, lows)}.")
    div = b.get("divergence")
    if div:
        lines.append(f"- **{div}**")
    # #2 Dispersion & correlation regime: one line at the end of internals.
    if regime_line:
        lines.append(f"- **{regime_line}**")
    return "\n".join(lines).strip()


def render_regime_line(metrics: Dict[str, Any]) -> str:
    """ONE plain-English line describing the cross-sectional dispersion &
    correlation regime (#2), e.g.:

      "Regime: Idiosyncratic tape - stock-picking rewarded (1W dispersion 4.8%,
       avg 20D pairwise corr 0.18)."

    Returns '' when no regime tag is available (an old snapshot / too few
    names). The two numbers are shown when present, otherwise dropped. Never
    raises."""
    reg = metrics.get("regime") or {}
    tag = reg.get("tag")
    if not tag:
        return ""
    disp = reg.get("xsec_dispersion_1w")
    corr = reg.get("avg_pairwise_corr_20d")
    bits: List[str] = []
    if disp is not None:
        bits.append(f"1W dispersion {_pct(disp).lstrip('+')}")
    if corr is not None:
        try:
            bits.append(f"avg 20D pairwise corr {float(corr):.2f}")
        except (TypeError, ValueError):
            pass
    tail = f" ({', '.join(bits)})" if bits else ""
    return f"Regime: {tag}{tail}."


def render_scorecard(metrics: Dict[str, Any], cap: int = 6) -> str:
    """The '### Scorecard - how prior calls played out' block (#5).

    Lists up to ``cap`` evaluated names as 'Company Name (TICKER): flagged {ret}
    on {asof} -> since {ret} [OK/miss]' plus the summary line. When there is
    insufficient history (nothing evaluable), prints the honest one-liner only.
    Returns '' when the hit_rate metrics are entirely absent. Never raises."""
    hr = metrics.get("hit_rate") or {}
    if not hr:
        return ""
    lines: List[str] = ["### Scorecard - how prior calls played out", ""]
    evaluated = hr.get("evaluated") or []
    n_eval = hr.get("n_evaluated") or 0
    if n_eval and evaluated:
        per = metrics.get("per_ticker") or {}
        for e in evaluated[:cap]:
            sym = e.get("symbol")
            rec = per.get(sym) or {"symbol": sym}
            mark = "OK" if e.get("hit") else "miss"
            lines.append(
                f"- {_descriptor(rec)}: flagged {_pct(e.get('flag_ret'))} on "
                f"{e.get('flagged_on')} \u2192 since {_pct(e.get('since_ret'))} "
                f"[{mark}]"
            )
        extra = len(evaluated) - min(len(evaluated), cap)
        if extra > 0:
            lines.append(f"- \u2026 and {extra} more evaluated.")
        lines.append("")
    summary = hr.get("summary")
    if summary:
        lines.append(f"_{summary}_")
    return "\n".join(lines).strip()


def _rotation_tag(sec: Dict[str, Any]) -> str:
    """Delta / rotation cell for the scoreboard: the rotation tag with its rank
    move when the sector rotated >= the threshold, else an em-dash. None-safe."""
    rot = sec.get("rotation")
    prev = sec.get("prev_rank")
    rank = sec.get("rank")
    if rot and prev is not None and rank is not None:
        return f"{rot} ({prev}\u2192{rank})"
    if rot:
        return str(rot)
    return "—"


def render_sector_scoreboard(metrics: Dict[str, Any]) -> str:
    """The '## Sector scoreboard' section body (#6): Sector | 1W med | YTD med |
    Breadth (a/d) | Δ (rotation tag). Returns '' when no sector data (an old
    snapshot without a sector column). Never raises."""
    sr = metrics.get("sector_rotation") or {}
    sectors = sr.get("sectors") or []
    if not sectors:
        return ""
    rows: List[List[str]] = []
    for s in sectors:
        rows.append([
            str(s.get("sector") or "—"),
            _pct(s.get("ret_1w_med")),
            _pct(s.get("ret_ytd_med")),
            f"{s.get('adv') or 0}/{s.get('dec') or 0}",
            _rotation_tag(s),
        ])
    body = _md_table(
        ["Sector", "1W med", "YTD med", "Breadth (a/d)", "Δ"], rows,
    )
    note = sr.get("note")
    if note:
        body += f"_Rotation tags: {note}._\n"
    return body


def _staleness_banner(metrics: Dict[str, Any]) -> str:
    """The prominent as-of block placed right under the note title. Returns a
    BOLD, standalone 'Data as of:' line so the reader can never miss which date
    the numbers reflect; when the snapshot is stale, a SECOND line carries the
    staleness warning (kept distinct from the bold as-of line, not merged into
    one italic line). Never raises."""
    asof = metrics.get("asof") or "unknown"
    n_stale = metrics.get("n_stale")
    asof_line = f"**Data as of: {asof}**"
    if metrics.get("stale"):
        return (asof_line + "\n\n"
                f"> \u26a0 Data is {n_stale} business days old; refresh the "
                "FactSet pull for a current read.")
    return asof_line


# ---------------------------------------------------------------------------
# Grouping: split movers into gainers / losers-stock-specific / losers-sector /
# stretched-to-extremes for the plain-English "What moved and why" section.
# ---------------------------------------------------------------------------
def _is_sector_driven(rec: Dict[str, Any]) -> bool:
    return (rec.get("attribution") or {}).get("attribution") == "Sector-driven"


def _group_movers(metrics: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Group the computed movers for the grouped narrative. Returns lists of the
    rich mover entries: gainers, losers_specific, losers_sector, extremes."""
    movers = metrics.get("movers") or {}
    gainers = list(movers.get("gainers_1w") or [])
    losers = list(movers.get("losers_1w") or [])
    losers_sector = [r for r in losers if _is_sector_driven(r)]
    losers_specific = [r for r in losers if not _is_sector_driven(r)]
    extremes = list(movers.get("extremes") or [])
    return {
        "gainers": gainers,
        "losers_specific": losers_specific,
        "losers_sector": losers_sector,
        "extremes": extremes,
    }


def _gainers_mostly_specific(gainers: List[Dict[str, Any]]) -> bool:
    tagged = [(r.get("attribution") or {}).get("attribution") for r in gainers]
    tagged = [t for t in tagged if t]
    if not tagged:
        return False
    return sum(1 for t in tagged if t == "Stock-specific") >= len(tagged) / 2.0


def _count_specific(metrics: Dict[str, Any]) -> Tuple[int, int]:
    """(# stock-specific, # total) among the top-10 1W movers (gainers+losers)."""
    movers = metrics.get("movers") or {}
    pool = list(movers.get("gainers_1w") or []) + list(movers.get("losers_1w") or [])
    tagged = [(r.get("attribution") or {}).get("attribution") for r in pool]
    tagged = [t for t in tagged if t]
    spec = sum(1 for t in tagged if t == "Stock-specific")
    return spec, len(tagged)


def render_grouped_movers(metrics: Dict[str, Any]) -> str:
    """Deterministic, plain-English grouped 'What moved and why' body. Used as
    the no-key fallback AND embedded in the AI prompt as the grounding set.
    Includes a short lead, then Gainers / Losers (stock-specific) / Losers
    (sector-driven) / Stretched to extremes blocks. Never raises."""
    g = _group_movers(metrics)
    spec, total = _count_specific(metrics)
    parts: List[str] = []
    # Short lead (2-3 sentences) leading with the conclusion.
    if total:
        if spec >= total - max(1, total // 4):
            lead = (f"This week's moves were overwhelmingly stock-specific "
                    f"(moved differently from sector peers) rather than sector "
                    f"rotation \u2014 {spec} of the {total} biggest movers can't be "
                    "explained by their peers.")
        elif spec <= total // 4:
            lead = ("This week's moves were largely sector-driven (the whole "
                    "sector moved together) rather than company-specific.")
        else:
            lead = (f"This week's moves were mixed: {spec} of the {total} biggest "
                    "movers were stock-specific, the rest moved with their sector.")
        parts.append(lead)

    def _block(title: str, recs: List[Dict[str, Any]]) -> None:
        if not recs:
            return
        parts.append(f"\n**{title}**")
        for r in recs:
            parts.append(f"- {_mover_line(r)}")

    gtitle = ("Gainers \u2014 almost entirely company-specific"
              if _gainers_mostly_specific(g["gainers"]) else "Gainers")
    _block(gtitle, g["gainers"])
    _block("Losers \u2014 stock-specific (moved differently from sector peers)",
           g["losers_specific"])
    _block("Losers \u2014 sector-driven (fell with the whole sector)", g["losers_sector"])
    # Stretched to extremes watchlist.
    if g["extremes"]:
        parts.append("\n**Stretched to extremes** (largest move vs the name's own "
                     "typical weekly swing \u2014 a mean-reversion watchlist)")
        ex_bits = []
        for r in g["extremes"]:
            sig = _sigma_str(r)
            ex_bits.append(f"{_descriptor(r)} ({sig})" if sig else _descriptor(r))
        parts.append("- " + "; ".join(ex_bits))
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Key takeaways (AI-generated; deterministic fallback)
# ---------------------------------------------------------------------------
def _breadth_context_line(metrics: Dict[str, Any]) -> str:
    """One grounded sentence summarizing breadth for the prompts / deterministic
    takeaways. '' when no breadth data."""
    b = metrics.get("breadth") or {}
    if not (b.get("n_valid") or 0):
        return ""
    br = b.get("breadth_ratio")
    br_txt = f"{float(br) * 100:.0f}%" if br is not None else "n/a"
    txt = (f"Breadth {b.get('advancers', 0)}/{b.get('decliners', 0)} up/down "
           f"(ratio {br_txt})")
    up_dv, down_dv = b.get("up_dollar_vol"), b.get("down_dollar_vol")
    if up_dv is not None or down_dv is not None:
        txt += (f", {fmt_dollars(up_dv)} traded up vs {fmt_dollars(down_dv)} "
                "down")
    if b.get("divergence"):
        txt += f". {b.get('divergence')}"
    else:
        txt += "."
    return txt


def _sector_context_line(metrics: Dict[str, Any]) -> str:
    """One grounded sentence: top sector leader + laggard + any rotation tag. ''
    when no sector data."""
    sr = metrics.get("sector_rotation") or {}
    sectors = sr.get("sectors") or []
    ranked = [s for s in sectors if s.get("ret_1w_med") is not None]
    if not ranked:
        return ""
    lead = ranked[0]
    lag = ranked[-1]
    txt = (f"Sector leader {lead.get('sector')} ({_pct(lead.get('ret_1w_med'))} "
           f"1W median), laggard {lag.get('sector')} "
           f"({_pct(lag.get('ret_1w_med'))})")
    rots = [f"{s.get('sector')} {s.get('rotation')}"
            for s in sectors if s.get("rotation")]
    if rots:
        txt += ". Rotation: " + "; ".join(rots)
    txt += "."
    return txt


def _scorecard_context_line(metrics: Dict[str, Any]) -> str:
    """One grounded sentence: the hit-rate summary. '' when there is nothing
    evaluated (insufficient history is NOT surfaced to takeaways). None-safe."""
    hr = metrics.get("hit_rate") or {}
    if not hr or not (hr.get("n_evaluated") or 0):
        return ""
    return str(hr.get("summary") or "").strip()


def build_takeaways_prompt(metrics: Dict[str, Any]) -> str:
    """Prompt for the KEY TAKEAWAYS box. Grounded ONLY in computed numbers (the
    grouped movers + HSI + attribution counts + extremes + breadth + sector
    rotation). Forbids invention."""
    asof = metrics.get("asof") or "the as-of date"
    hsi = metrics.get("hsi") or {}
    grouped = render_grouped_movers(metrics)
    spec, total = _count_specific(metrics)
    breadth_line = _breadth_context_line(metrics)
    sector_line = _sector_context_line(metrics)
    hsi_line = (f"HSI {_pct(hsi.get('ret_1w'))} on the week, {_pct(hsi.get('ret_ytd'))} "
                f"YTD, short trend {hsi.get('trend') or 'n/a'}.")
    regime_line = render_regime_line(metrics)
    scorecard_line = _scorecard_context_line(metrics)
    extra_ctx = ""
    if breadth_line:
        extra_ctx += f"\nMarket breadth (computed): {breadth_line}\n"
    if sector_line:
        extra_ctx += f"Sector scoreboard (computed): {sector_line}\n"
    if regime_line:
        extra_ctx += f"Dispersion & correlation regime (computed): {regime_line}\n"
    if scorecard_line:
        extra_ctx += f"Prior-call scorecard (computed): {scorecard_line}\n"
    return (
        "You are an equity strategist writing the KEY TAKEAWAYS box at the TOP of "
        f"a weekly one-pager for a Hang Seng (HSI) universe, as of {asof}.\n\n"
        "Write 4-6 short, punchy bullets that synthesize the week, GROUNDED ONLY "
        "in the computed figures below. Cover, where the data supports it: (1) the "
        "dominant pattern \u2014 stock-specific vs sector rotation (the count is "
        f"{spec} of {total} biggest movers stock-specific); (2) the single most "
        "extreme dislocation by sigma \u2014 and where the data supports it, put that "
        "dislocation in RISK-ADJUSTED MOMENTUM context (its move relative to the "
        "name's own typical swing / risk-adjusted 3M momentum), NOT just the raw "
        "sigma number; (3) any genuinely sector-driven names; (4) a VALUATION ANCHOR "
        "for at least ONE named mover when available \u2014 whether it screens cheap or "
        "rich versus its sector on forward P/E; (5) red flags such as big "
        "EPS-estimate cuts. "
        "You MUST also include (6) an explicit WATCH ITEM bullet flagging something "
        "to monitor next week \u2014 e.g. an unresolved EPS cut, a stock-specific "
        "dislocation with no catalyst yet found, or a sector showing early rotation "
        "signs; begin it with 'Watch:' so it is unmistakable. "
        "Refer to each name by its COMPANY NAME with the "
        "ticker in parentheses, e.g. 'Some Company (9636-HK)', not bare codes and "
        "not the sector in the parentheses. "
        "Reference the HSI figure ONCE. Where the data supports it, you MAY also "
        "cite MARKET BREADTH (e.g. a narrow tape / hidden strength divergence, or "
        "whether dollar volume flowed with the winners or the losers) and the "
        "SECTOR SCOREBOARD (which sector led/lagged, and any 'rotation in/out' "
        "tag) from the computed context below \u2014 but only when it adds signal. "
        "Do NOT invent tickers, prices, news, or "
        "catalysts \u2014 every number must come from below; never fabricate a "
        "valuation, momentum or watch fact the figures do not support. Output ONLY "
        "the bullets, each starting with '- '.\n\n"
        f"HSI: {hsi_line}\n"
        f"{extra_ctx}\n"
        f"Grouped movers (computed):\n{grouped}\n"
    )


def render_takeaways_deterministic(metrics: Dict[str, Any]) -> str:
    """Deterministic KEY TAKEAWAYS bullets, assembled from the computed extremes /
    attribution counts / HSI / EPS cuts. Used when no AI key is available. Never
    raises; always returns at least one bullet when any data is present."""
    hsi = metrics.get("hsi") or {}
    movers = metrics.get("movers") or {}
    g = _group_movers(metrics)
    spec, total = _count_specific(metrics)
    bullets: List[str] = []

    # (1) Market backdrop + dominant pattern.
    if hsi.get("ret_1w") is not None or total:
        trend = hsi.get("trend") or "n/a"
        market = (f"The market moved {_pct(hsi.get('ret_1w'))} on the week "
                  f"({_pct(hsi.get('ret_ytd'))} YTD, {trend})")
        if total:
            if spec >= total - max(1, total // 4):
                pat = (f", but this week's movers were mostly company-specific, not "
                       f"sector rotation \u2014 {spec} of the {total} biggest movers "
                       "can't be explained by their peers.")
            elif spec <= total // 4:
                pat = ", and this week's moves were largely sector-driven."
            else:
                pat = (f", with a mix this week \u2014 {spec} of {total} biggest movers "
                       "were company-specific.")
        else:
            pat = "."
        bullets.append(market + pat)

    # (2) Cleanest dislocation by sigma.
    if g["extremes"]:
        top = g["extremes"][0]
        sig = _sigma_str(top)
        if sig:
            bullets.append(
                f"Cleanest dislocation: {_descriptor(top)} {_pct(top.get('ret_1w'))}, "
                f"{sig} vs its own history \u2014 an extreme that sometimes mean-reverts."
            )

    # (3) Genuinely sector-driven names.
    if g["losers_sector"]:
        names = ", ".join(_descriptor(r) for r in g["losers_sector"][:3])
        bullets.append(
            f"Genuinely sector-driven: {names} moved with their sector peers, so "
            "less likely to bounce alone."
        )

    # (3b) Valuation anchor for the top mover, when a fwd-P/E-vs-sector read is
    # available. Surfaces cheap/rich context so the deterministic path is not
    # purely momentum-driven. Prefer the top gainer; fall back to the top
    # extreme so we anchor the most salient name on the page.
    val_pool = list(g["gainers"]) + list(g["extremes"])
    val_anchored = next(
        (r for r in val_pool if _val_anchor(r) and r.get("valuation_vs_sector")),
        None,
    )
    if val_anchored is not None:
        vs = val_anchored.get("valuation_vs_sector")
        bullets.append(
            f"Valuation: {_descriptor(val_anchored)} screens {vs} at forward P/E "
            f"{_val_anchor(val_anchored)} vs its sector."
        )

    # (4) Red flag: biggest EPS-estimate cut among movers.
    pool = list(movers.get("gainers_1w") or []) + list(movers.get("losers_1w") or [])
    cuts = [r for r in pool
            if r.get("eps_revision_dir") == "down" and r.get("eps_revision_pct") is not None]
    if cuts:
        worst = min(cuts, key=lambda r: r.get("eps_revision_pct"))
        bullets.append(
            f"Red flag: {_descriptor(worst)} saw analysts cut EPS estimates "
            f"{_pct(worst.get('eps_revision_pct'))} over 4 weeks \u2014 fundamentals "
            "deteriorating, not just price."
        )

    # (5) Watch item: name the least-resolved dislocation to monitor next week.
    # Prefer an unresolved EPS cut; else the most extreme stock-specific
    # dislocation with no catalyst yet identified (the catalyst step runs later,
    # so at this point every dislocation is "unresolved"). Always deterministic.
    watch = None
    if cuts:
        worst_cut = min(cuts, key=lambda r: r.get("eps_revision_pct"))
        watch = (
            f"Watch: whether the EPS cut at {_descriptor(worst_cut)} "
            f"({_pct(worst_cut.get('eps_revision_pct'))} over 4 weeks) keeps "
            "pressuring the price into next week."
        )
    elif g["extremes"]:
        top = g["extremes"][0]
        sig = _sigma_str(top)
        sig_txt = f" ({sig} vs its own history)" if sig else ""
        watch = (
            f"Watch: {_descriptor(top)}{sig_txt} is the least-resolved dislocation "
            "\u2014 no catalyst confirmed yet; monitor for follow-through or reversal."
        )
    if watch:
        bullets.append(watch)

    # (6) Market breadth line (when breadth present) — lead with any divergence.
    b = metrics.get("breadth") or {}
    if (b.get("n_valid") or 0):
        br = b.get("breadth_ratio")
        br_txt = f"{float(br) * 100:.0f}%" if br is not None else "n/a"
        if b.get("divergence"):
            bullets.append(f"Breadth: {b.get('divergence')} "
                           f"({b.get('advancers', 0)} up / {b.get('decliners', 0)} "
                           f"down, ratio {br_txt}).")
        else:
            bullets.append(
                f"Breadth: {b.get('advancers', 0)} names up vs "
                f"{b.get('decliners', 0)} down (ratio {br_txt}) \u2014 the tape's "
                "internals under the index move."
            )

    # (7) Sector leader / laggard line (when the scoreboard has data).
    sr = metrics.get("sector_rotation") or {}
    ranked = [s for s in (sr.get("sectors") or [])
              if s.get("ret_1w_med") is not None]
    if ranked:
        lead = ranked[0]
        lag = ranked[-1]
        sent = (f"Sectors: {lead.get('sector')} led "
                f"({_pct(lead.get('ret_1w_med'))} 1W median) and "
                f"{lag.get('sector')} lagged ({_pct(lag.get('ret_1w_med'))})")
        rots = [f"{s.get('sector')} {s.get('rotation')}"
                for s in ranked if s.get("rotation")]
        if rots:
            sent += "; rotation: " + ", ".join(rots)
        sent += "."
        bullets.append(sent)

    # (8) Dispersion & correlation regime line (when a regime read exists).
    regime_line = render_regime_line(metrics)
    if regime_line:
        bullets.append(regime_line)

    # (9) Prior-call scorecard summary (only when something was evaluated).
    scorecard_line = _scorecard_context_line(metrics)
    if scorecard_line:
        bullets.append(f"Scorecard: {scorecard_line}")

    if not bullets:
        bullets.append("Not enough loaded data to synthesize takeaways this week.")
    return "\n".join(f"- {b}" for b in bullets)


# ---------------------------------------------------------------------------
# Inline glossary block (renders cleanly in md/html/docx/pdf)
# ---------------------------------------------------------------------------
GLOSSARY_HEADING = "Glossary & methodology"
_GLOSSARY_TERMS: List[Tuple[str, str]] = [
    ("fwd P/E", "forward price-to-earnings: latest price divided by the consensus "
     "next-fiscal-year EPS estimate (blank when EPS is zero/negative/missing)."),
    ("vs sector", "the name's forward P/E compared with the MEDIAN forward P/E of "
     "every loaded name in its broad FactSet sector; cheap < 0.85x that median, "
     "rich > 1.15x, otherwise in line."),
    ("stock-specific", "the name moved differently from its sector peers, so the "
     "move is mostly company-specific rather than a sector-wide move."),
    ("sector-driven", "the name moved roughly in line with its sector peers, so "
     "the move looks driven by the sector, not the company."),
    ("sigma", "how unusual the weekly move is versus the name's OWN typical "
     "weekly swing; e.g. -5.7 sigma means 5.7 standard deviations below its usual move."),
    ("vs HSI", "the name's return minus the Hang Seng Index return over the same "
     "window (relative performance)."),
    ("EPS revision", "the change in the consensus FY1 EPS estimate over the past "
     "~4 weeks (up = upgrades, down = cuts)."),
    ("beta", "how much the stock tends to move for a given index move: beta 1.5 "
     "means it typically swings 1.5x the HSI (estimated from ~60 days of daily "
     "returns)."),
    ("alpha (1W)", "the part of the week's move NOT explained by the market: the "
     "stock's 1W return minus beta times the HSI's 1W return \u2014 positive alpha "
     "beat what its market sensitivity alone predicted."),
    ("$ADV", "average daily dollar volume over the trailing 20 days (price x "
     "shares traded); a rough gauge of how much can be traded without moving the "
     "price \u2014 a big move on thin $ADV is harder to trade at size."),
    ("breadth", "how many names rose vs fell on the week; breadth ratio = "
     "advancers / (advancers + decliners). Low breadth while the index rises "
     "means gains are concentrated in a few names (a narrow tape)."),
    ("dispersion", "how widely the names' weekly returns are spread out this "
     "week (the standard deviation of every name's 1W move). Wide dispersion "
     "means winners and losers diverged a lot \u2014 a stock-picker's tape; tight "
     "dispersion means most names moved together."),
    ("pairwise correlation", "how closely the names moved together day-to-day "
     "over the last ~20 days, averaged across every pair. High correlation "
     "(near 1) means a macro-driven tape where names rise and fall together and "
     "stock-picking adds little; low correlation means names moved on their own "
     "stories."),
    ("scorecard", "a look-back at the extreme dislocations flagged in prior "
     "weekly notes: how many have since moved OPPOSITE to the flagged move "
     "(begun mean-reverting) by at least a quarter of that move. Measurement "
     "only \u2014 not a trade record."),
]


def render_glossary() -> str:
    """A compact glossary rendered as clean markdown PARAGRAPHS (one bold term +
    definition per line). Deliberately NOT a wide table so it can never overflow
    / fragment the PDF page. Never raises."""
    lines = [f"### {GLOSSARY_HEADING}", ""]
    for term, defn in _GLOSSARY_TERMS:
        lines.append(f"- **{term}** \u2014 {defn}")
    lines.append("")
    lines.append("_Returns are simple % price change. Attribution nets each move "
                 "against a leave-one-out peer median. Educational tool, not "
                 "investment advice._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Catalyst structuring: collapse "no catalyst" noise into a single line.
# ---------------------------------------------------------------------------
_NO_CATALYST_RE = re.compile(
    r"no (?:specific |company[- ]specific )?(?:news )?catalyst|nothing specific|"
    r"no clear catalyst|no identifiable catalyst|no obvious catalyst",
    re.IGNORECASE,
)
_INFERRED_RE = re.compile(r"inferred|low[- ]confidence|likely (?:fell|rose|moved) with|"
                          r"sector[- ]driven|broad .*sector", re.IGNORECASE)


def _strip_bullet(line: str) -> str:
    return re.sub(r"^\s*[-*\u2022]\s*", "", line).strip()


def _extract_symbol(line: str, names: List[str]) -> Optional[str]:
    """Find which known symbol (or its bare code) a model line refers to."""
    low = line.lower()
    for sym in names:
        if sym.lower() in low:
            return sym
        bare = sym.split("-")[0]
        if bare and re.search(rf"\b{re.escape(bare.lower())}\b", low):
            return sym
    return None


def collapse_catalysts(raw: str, metrics: Dict[str, Any]) -> str:
    """Post-process the model's per-name catalyst output: emit ONE collapsed line
    for all names with no catalyst, full bullets for names with a real cited
    catalyst, and a clearly-flagged low-confidence group for inferred sector
    explanations. Falls back to the raw text if it can't parse anything. Never
    raises."""
    names = list(metrics.get("catalyst_names") or [])

    def _bare(sym: str) -> str:
        return sym.split("-")[0] or sym

    found: List[str] = []          # full bullets (real catalyst)
    inferred: List[str] = []       # sector-driven / low-confidence lines
    none_found: List[str] = []     # bare codes for the collapsed line
    seen: set = set()

    lines = [l for l in (raw or "").splitlines() if l.strip()]
    parsed_any = False
    for line in lines:
        body = _strip_bullet(line)
        if not body:
            continue
        sym = _extract_symbol(body, names)
        if sym is None:
            continue
        parsed_any = True
        if sym in seen:
            continue
        seen.add(sym)
        if _NO_CATALYST_RE.search(body):
            none_found.append(_bare(sym))
        elif _INFERRED_RE.search(body):
            # Avoid double-prefixing when the model already led with the symbol
            # (e.g. "BBB: likely moved with Energy ...").
            stripped = re.sub(rf"^\s*{re.escape(sym)}\s*:\s*", "", body,
                              flags=re.IGNORECASE)
            stripped = re.sub(rf"^\s*{re.escape(_bare(sym))}\s*:\s*", "",
                              stripped, flags=re.IGNORECASE)
            inferred.append(f"{_bare(sym)}: {stripped}")
        else:
            found.append(f"- {body}")

    # Names the model never mentioned -> treat as none-found.
    for sym in names:
        if sym not in seen:
            none_found.append(_bare(sym))

    if not parsed_any and (raw or "").strip():
        # Couldn't map anything; return the model text unchanged (still useful).
        return raw.strip()

    out: List[str] = []
    for b in found:
        out.append(b)
    if none_found:
        uniq = list(dict.fromkeys(none_found))
        out.append(
            "No company-specific news catalyst found for: "
            + ", ".join(uniq)
            + " \u2014 moves appear driven by flows, momentum, or estimate changes."
        )
    if inferred:
        out.append("")
        out.append("_Sector-driven (inferred, low confidence):_")
        for it in inferred:
            out.append(f"- {it}")
        out.append("_Inferences from peer behavior, not reported news._")
    return "\n".join(out).strip()


def render_catalysts_deterministic(metrics: Dict[str, Any]) -> str:
    """No-web fallback for the catalysts section: we have no news, so collapse ALL
    names into the single 'no catalyst found' line, and flag the sector-driven
    names as low-confidence inferences from peer behavior."""
    names = list(metrics.get("catalyst_names") or [])
    per = metrics.get("per_ticker") or {}
    if not names:
        return ""
    bare = [s.split("-")[0] or s for s in names]
    out = [
        "No company-specific news catalyst found (no web access this run) for: "
        + ", ".join(bare)
        + " \u2014 moves appear driven by flows, momentum, or estimate changes."
    ]
    inferred = [s for s in names
                if (per.get(s, {}).get("attribution") or {}).get("attribution")
                == "Sector-driven"]
    if inferred:
        out.append("")
        out.append("_Sector-driven (inferred, low confidence):_")
        for s in inferred:
            rec = per.get(s, {})
            sec = _short_sector(rec) or "its sector"
            out.append(f"- {s.split('-')[0]} likely moved with broad {sec} pressure.")
        out.append("_Inferences from peer behavior, not reported news._")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Prompt builders (pure)
# ---------------------------------------------------------------------------
def _mover_data_lines(metrics: Dict[str, Any]) -> str:
    """Per-name grounded data lines for the highlighted movers, carrying $ADV
    (advv_20d), beta and alpha alongside the 1W move, so the model can apply the
    tradeability caveat and alpha language. Deduped over gainers+losers+extremes.
    '' when no movers. None-safe."""
    movers = metrics.get("movers") or {}
    per = metrics.get("per_ticker") or {}
    pool: List[Dict[str, Any]] = []
    seen: set = set()
    for grp in ("gainers_1w", "losers_1w", "extremes"):
        for r in movers.get(grp, []) or []:
            sym = r.get("symbol")
            if sym and sym not in seen:
                seen.add(sym)
                pool.append(r)
    lines: List[str] = []
    for r in pool:
        sym = r.get("symbol")
        m = per.get(sym, {}) or {}
        advv = r.get("advv_20d")
        if advv is None:
            advv = m.get("advv_20d")
        thin = (advv is not None and advv < wmetrics.THIN_ADV_DOLLARS)
        thin_txt = " [THIN: below $25m ADV]" if thin else ""
        lines.append(
            f"- {_descriptor(r)}: 1W {_pct(r.get('ret_1w'))}, "
            f"$ADV {fmt_dollars(advv)}{thin_txt}, "
            f"beta {_num(r.get('beta_60d') if r.get('beta_60d') is not None else m.get('beta_60d'))}, "
            f"alpha(1W) {_pct(r.get('alpha_1w') if r.get('alpha_1w') is not None else m.get('alpha_1w'))}."
        )
    return "\n".join(lines)


def build_observations_prompt(metrics: Dict[str, Any]) -> str:
    asof = metrics.get("asof") or "the as-of date"
    grouped = render_grouped_movers(metrics)
    tables = render_metric_tables(metrics)
    spec, total = _count_specific(metrics)
    data_lines = _mover_data_lines(metrics)
    return (
        "You are an equity strategist writing the WHAT MOVED AND WHY section of a "
        f"weekly one-pager for a Hang Seng (HSI) universe, as of {asof}. Write for "
        "a smart generalist, NOT a quant: PLAIN ENGLISH, no jargon left "
        "unexplained.\n\n"
        "STRUCTURE (lead with the conclusion):\n"
        "1. Open with ONE short sentence stating the dominant pattern of the week "
        f"-- were the big moves company-specific or sector-wide? (The computed "
        f"count: {spec} of {total} biggest movers were stock-specific.)\n"
        "2. Then GROUP the movers under short bold headings -- Gainers; Losers "
        "(stock-specific); Losers (sector-driven); Stretched to extremes -- one "
        "tight bullet per name.\n\n"
        "RULES:\n"
        "- Refer to each name by its COMPANY NAME with the ticker in parentheses, "
        "e.g. 'Some Company (9636-HK)', never a bare code and never the sector in "
        "the parentheses. You may still mention the sector in the surrounding "
        "sentence when relevant.\n"
        "- When a valuation anchor is given, state it plainly, e.g. 'trades cheap "
        "at 11.8x vs the sector's ~9x'. Define forward P/E in plain words on first "
        "use.\n"
        "- ADD DEPTH for the TOP 1-2 names in EACH group (not just return + peer "
        "attribution): where the figures provide it, weave in the VALUATION-VS-"
        "SECTOR read (cheap / in line / rich on forward P/E) AND the earnings "
        "MOMENTUM / REVISION context (EPS estimates revised up or down, and by how "
        "much) for those lead names, so each group's headline name has a fundamental "
        "as well as a price story.\n"
        "- CALL OUT VOLUME CONFIRMATION explicitly for any name where volume "
        "behavior adds or undercuts conviction: a big volume spike WITHOUT price "
        "follow-through (weak conviction / possible churn), or a large price move "
        "WITHOUT volume confirmation (thin, less reliable). Say plainly whether the "
        "volume supports or questions the move.\n"
        "- TRADEABILITY CAVEAT: for any highlighted mover whose $ADV (dollar 20D "
        "average daily volume) is below $25m \u2014 marked [THIN] in the per-name "
        "data \u2014 add a short caveat that it is thin: a large move on thin "
        "liquidity is harder to trade at size. Use the given $ADV number; do not "
        "invent one.\n"
        "- ALPHA LANGUAGE: for the lead names, use the beta / alpha(1W) figures. "
        "Alpha is the part of the move NOT explained by the market (return minus "
        "beta times the HSI move). When a name's 1W return is LARGE but its "
        "alpha(1W) is SMALL, say the move was mostly BETA / market-explained, NOT "
        "stock-specific; when alpha is large, the name genuinely out/underperformed "
        "its market sensitivity.\n"
        "- Translate attribution into plain English: 'stock-specific' means it "
        "moved differently from its sector peers; 'sector-driven' means it moved "
        "with them.\n"
        "- Mention an EPS-estimate cut/raise only when the figure is given.\n"
        "- Ground EVERYTHING strictly in the computed figures below -- do NOT "
        "invent tickers, prices, news, or catalysts (a separate section covers "
        "catalysts). Write n/a where a fundamental is missing.\n"
        "- Do NOT discuss the HSI index level itself (a separate macro section "
        "does that).\n\n"
        "Grouped movers (already computed -- rewrite into flowing prose + bullets, "
        "do not just copy):\n"
        f"{grouped}\n\n"
        "Per-name liquidity & risk-adjusted data ($ADV, beta, alpha \u2014 use for "
        "the tradeability caveat and alpha language):\n"
        f"{data_lines or '(none)'}\n\n"
        "Full computed tables for reference (figures only):\n"
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
        "For each name, look for: earnings or guidance, M&A, regulatory/policy "
        "news, sector flows, index inclusion/exclusion or rebalance, "
        "ex-dividend/forced flow.\n\n"
        "OUTPUT FORMAT — EXACTLY ONE LINE PER NAME so the app can group them, each "
        "starting with the bare symbol then a colon:\n"
        "- If you found a real, citable catalyst: '<SYM>: <one-sentence catalyst>'.\n"
        "- If web search yields NOTHING specific for the name: write the literal "
        "phrase '<SYM>: no specific catalyst found'. Do NOT fabricate.\n"
        "- If the move only plausibly reflects a SECTOR/MACRO driver (not reported "
        "company news): '<SYM>: likely moved with <sector> on <driver> (inferred, "
        "low confidence)'.\n"
        "Keep each line to one sentence. No headers, no preamble.\n\n"
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
        "You are a macro strategist writing the TOP-DOWN INDEX section of a weekly "
        f"one-pager on the Hang Seng Index (HSI), as of {asof}. Your job is to "
        "INTERPRET the index week at the macro level only.\n\n"
        "State the HSI's weekly figure AT MOST ONCE, then spend the rest on what "
        "is driving the INDEX: China macro data, PBoC/HKMA policy, Stock Connect "
        "flows, sector rotation, and the broad risk backdrop. Keep it to 1-2 "
        "short paragraphs.\n\n"
        "DO NOT restate or re-list the individual-stock movers — a separate "
        "'What moved and why' section already covers single names. DO NOT repeat "
        "the HSI percentage multiple times. If you have live web context, fold in "
        "the macro/policy/flow drivers; otherwise interpret strictly from the "
        "computed move and do not fabricate news. Plain prose, no headers.\n\n"
        f"{computed}\n"
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _no_key_markdown(metrics: Dict[str, Any]) -> str:
    """No-AI-key deliverable: deterministic takeaways box + grouped plain-English
    movers + collapsed (no-web) catalysts + glossary + the always-on metric
    tables. Must NOT contain the AI-only '## Data observations' heading."""
    banner = _staleness_banner(metrics)
    takeaways = render_takeaways_deterministic(metrics)
    grouped = render_grouped_movers(metrics)
    catalysts = render_catalysts_deterministic(metrics)
    glossary = render_glossary()
    tables = render_metric_tables(metrics)
    parts: List[str] = [f"# {TITLE}", "", banner, ""]
    parts += [
        "> Set an AI key in Settings for the AI-written synthesis. The takeaways, "
        "plain-English movers and computed metrics below are generated "
        "deterministically and are always available.",
        "",
    ]
    if takeaways.strip():
        parts += ["## Key takeaways", "", takeaways.strip(), ""]
    if grouped.strip():
        parts += ["## What moved and why", "", grouped.strip(), ""]
    if catalysts.strip():
        parts += ["## Catalysts", "", catalysts.strip(), ""]
    internals = render_market_internals(metrics)
    scorecard = render_scorecard(metrics)
    if internals.strip() or scorecard.strip():
        parts += ["## Market internals", ""]
        if internals.strip():
            parts += [internals.strip(), ""]
        # #5 Scorecard: how prior flagged calls played out (inside internals).
        if scorecard.strip():
            parts += [scorecard.strip(), ""]
    scoreboard = render_sector_scoreboard(metrics)
    if scoreboard.strip():
        parts += ["## Sector scoreboard", "", scoreboard.strip(), ""]
    parts += [glossary, ""]
    parts += ["## Computed metrics", "", tables]
    return "\n".join(parts)


def _assemble(
    metrics: Dict[str, Any],
    takeaways: str,
    observations: str,
    catalysts: str,
    hsi_commentary: str,
    notice: str,
) -> str:
    """New reading order: Key takeaways box -> What moved and why (grouped) ->
    Catalysts (collapsed) -> HSI macro view (deduped) -> Glossary -> Computed
    metrics. The exact heading strings '## Data observations', '## Catalysts
    (web)', '## HSI macro view', '## Computed metrics' are preserved (tests +
    exporter contract)."""
    banner = _staleness_banner(metrics)
    parts: List[str] = [f"# {TITLE}", "", banner, ""]
    if notice:
        parts += [f"> {notice}", ""]
    if takeaways.strip():
        parts += ["## Key takeaways", "", takeaways.strip(), ""]
    if observations.strip():
        # The AI-written 'what moved and why' body. Heading kept verbatim.
        parts += ["## Data observations", "", observations.strip(), ""]
    if catalysts.strip():
        parts += ["## Catalysts (web)", "", catalysts.strip(), ""]
    if hsi_commentary.strip():
        parts += ["## HSI macro view", "", hsi_commentary.strip(), ""]
    # Market internals (breadth / up-down $vol / new highs-lows / divergence) and
    # the sector scoreboard sit AFTER the macro view, BEFORE the glossary. Both
    # omit themselves when their underlying data is absent.
    internals = render_market_internals(metrics)
    scorecard = render_scorecard(metrics)
    if internals.strip() or scorecard.strip():
        parts += ["## Market internals", ""]
        if internals.strip():
            parts += [internals.strip(), ""]
        # #5 Scorecard: how prior flagged calls played out (inside internals).
        if scorecard.strip():
            parts += [scorecard.strip(), ""]
    scoreboard = render_sector_scoreboard(metrics)
    if scoreboard.strip():
        parts += ["## Sector scoreboard", "", scoreboard.strip(), ""]
    # Inline glossary so every term used above has a plain-English definition.
    parts += [render_glossary(), ""]
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

    # (a0) Key takeaways box [SYNTHESIS] -- AI when a synthesis provider exists,
    # otherwise the deterministic version. Always degrade gracefully.
    takeaways = ""
    if synth_ok:
        try:
            text, _used = complete_with_fallback(
                provider, build_takeaways_prompt(metrics),
                fallback_providers=fallback_providers,
                section="weekly_takeaways", max_tokens=400,
            )
            takeaways = (text or "").strip()
            _log_usage(provider, "sidebar", ok=True, note="weekly takeaways")
        except Exception as e:  # noqa: BLE001
            errors.append(f"takeaways: {e}")
            _log_usage(provider, "sidebar", ok=False, note=str(e)[:200])
    if not takeaways:
        takeaways = render_takeaways_deterministic(metrics)

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

    # (b) Web catalysts [WEB] -- route to the resolved web runner, then COLLAPSE
    # the per-name output into one 'no catalyst found' line + real-catalyst
    # bullets + a low-confidence inferred group. When no web ran, use the
    # deterministic collapsed line so the section is still informative.
    catalysts = ""
    if do_web and (metrics.get("catalyst_names") or []):
        try:
            text, _used = complete_with_fallback(
                web_runner, build_catalyst_prompt(metrics),
                fallback_providers=[],
                section="weekly_catalysts", max_tokens=800,
            )
            catalysts = collapse_catalysts((text or "").strip(), metrics)
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

    markdown = _assemble(
        metrics, takeaways, observations, catalysts, hsi_commentary, notice
    )

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
