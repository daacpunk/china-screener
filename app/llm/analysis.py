"""Build prompts from screen rows and run optional LLM synthesis.

Never crashes the screen: if a provider is missing or errors, returns a
structured result with an error note instead.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import LLMProvider

_METHODOLOGY = (
    "METHODOLOGY CONTEXT (do NOT recompute): The RSI(14), MACD, and "
    "volatility-normalized return z-scores were already computed in-app. "
    "Two non-overlapping horizons are used: 1-week (last 5 trading days) and "
    "1-month-ex-last-week (day -21 to -5). z = (r_horizon - mu_daily*h)/(sigma_daily*sqrt(h)). "
    "peer_relative_z compares a name's z to its GICS sub-industry peer median; "
    "|peer_relative_z| >= threshold => IDIOSYNCRATIC, else SECTOR/MACRO/POLICY. "
    "Your job is QUALITATIVE synthesis and context — NOT to recalculate signals."
)


def _row_line(r: Dict[str, Any]) -> str:
    def f(x, nd=2):
        try:
            return f"{float(x):.{nd}f}"
        except Exception:
            return "n/a"
    return (
        f"- {r.get('ticker')} ({r.get('name')}) | {r.get('sector')}/{r.get('sub_industry')} "
        f"| 1w z={f(r.get('z_1w'))} 1m-ex-wk z={f(r.get('z_1m_ex_week'))} "
        f"| dist20d={f(r.get('dist_from_sma'))} RSI={f(r.get('rsi'),1)} "
        f"MACD={r.get('macd_state')} peer_rel_z={f(r.get('peer_relative_z'))} "
        f"tag={r.get('dislocation_type')} event_flag={r.get('event_flag')}"
    )


def build_per_name_prompt(row: Dict[str, Any], playbook: str) -> str:
    return (
        f"{_METHODOLOGY}\n\n"
        f"You are an equity strategist. Playbook: {playbook}.\n"
        f"For the single name below, give a concise (3-4 sentence) qualitative note: "
        f"likely driver of the move, whether it looks like a genuine reversion candidate "
        f"vs a broken/structural story, idiosyncratic vs sector, and key risks/catalysts.\n\n"
        f"{_row_line(row)}\n"
    )


def build_portfolio_prompt(oversold: List[Dict], overbought: List[Dict]) -> str:
    os_lines = "\n".join(_row_line(r) for r in oversold[:15]) or "(none)"
    ob_lines = "\n".join(_row_line(r) for r in overbought[:15]) or "(none)"
    return (
        f"{_METHODOLOGY}\n\n"
        "You are a portfolio strategist. Synthesize the screen below into: "
        "(1) top 3 idiosyncratic oversold-reversion LONGS, (2) top 3 overbought-fade SHORTS, "
        "(3) grouping by sector & conviction, (4) explicit caveats and risk callouts. "
        "Be concise and structured with markdown headers.\n\n"
        f"## Oversold-Reversion candidates\n{os_lines}\n\n"
        f"## Overbought-Fade candidates\n{ob_lines}\n"
    )


def build_sidebar_prompt(
    oversold: List[Dict], overbought: List[Dict], master: Optional[List[Dict]] = None
) -> str:
    """Prompt for the Results right-sidebar synthesis. Built from the ACTUAL
    screen rows (never fabricated values)."""
    master = master or []
    os_lines = "\n".join(_row_line(r) for r in oversold[:10]) or "(none)"
    ob_lines = "\n".join(_row_line(r) for r in overbought[:10]) or "(none)"
    n_idio = sum(1 for r in master if r.get("dislocation_type") == "IDIOSYNCRATIC")
    n_sector = sum(1 for r in master if r.get("dislocation_type") and r.get("dislocation_type") != "IDIOSYNCRATIC")
    n_event = sum(1 for r in master if r.get("event_flag"))
    return (
        f"{_METHODOLOGY}\n\n"
        "You are an equity strategist writing a CONCISE right-sidebar briefing "
        "(<= ~220 words) that explains what THIS screen result means. Use short "
        "markdown sections with bold mini-headers. Cover, grounded ONLY in the rows below: "
        "(1) the most dislocated names, (2) idiosyncratic vs sector/macro breakdown, "
        "(3) key risks / event flags, (4) the top longs (oversold-reversion) and top "
        "fades (overbought). Do not invent tickers, prices, or fundamentals.\n\n"
        f"Screen summary: {len(master)} names screened; {n_idio} idiosyncratic, "
        f"{n_sector} sector/macro; {n_event} with event flags; "
        f"{len(oversold)} oversold-reversion longs; {len(overbought)} overbought fades.\n\n"
        f"## Oversold-Reversion (longs)\n{os_lines}\n\n"
        f"## Overbought-Fade (shorts)\n{ob_lines}\n"
    )


def synthesize_sidebar(
    provider: Optional[LLMProvider],
    oversold: List[Dict],
    overbought: List[Dict],
    master: Optional[List[Dict]] = None,
    max_tokens: int = 600,
) -> Dict[str, Any]:
    """Run the sidebar synthesis. Key-gated and crash-proof.

    Returns dict: {enabled, markdown, error, provider}. With provider=None (no
    key/disabled) returns a clean disabled hint and never raises.
    """
    if provider is None or not getattr(provider, "available", False):
        return {
            "enabled": False,
            "markdown": "",
            "error": "Set an AI key in Settings to enable synthesis.",
            "provider": None,
        }
    try:
        text = provider.complete(
            build_sidebar_prompt(oversold, overbought, master), max_tokens=max_tokens
        )
        return {"enabled": True, "markdown": text or "", "error": "",
                "provider": getattr(provider, "name", "")}
    except Exception as e:  # noqa: BLE001
        return {
            "enabled": True,
            "markdown": "",
            "error": f"Synthesis unavailable: {type(e).__name__}.",
            "provider": getattr(provider, "name", ""),
        }


def analyze_rows(
    provider: Optional[LLMProvider],
    oversold: List[Dict],
    overbought: List[Dict],
    per_name: bool = True,
    max_names: int = 6,
) -> Dict[str, Any]:
    """Run analysis. Returns dict with 'enabled', 'error', 'per_name', 'portfolio'."""
    if provider is None or not getattr(provider, "available", False):
        return {
            "enabled": False,
            "error": "No LLM provider/key configured. Add a key in Settings to enable AI analysis.",
            "per_name": [],
            "portfolio": "",
        }
    notes: List[Dict[str, str]] = []
    errors: List[str] = []
    if per_name:
        for r in (oversold[:max_names]):
            try:
                notes.append({"ticker": r.get("ticker"), "playbook": "Oversold-Reversion (long)",
                              "note": provider.complete(build_per_name_prompt(r, "Oversold-Reversion long"), max_tokens=300)})
            except Exception as e:  # noqa: BLE001
                errors.append(f"{r.get('ticker')}: {e}")
        for r in (overbought[:max_names]):
            try:
                notes.append({"ticker": r.get("ticker"), "playbook": "Overbought-Fade (short)",
                              "note": provider.complete(build_per_name_prompt(r, "Overbought-Fade short"), max_tokens=300)})
            except Exception as e:  # noqa: BLE001
                errors.append(f"{r.get('ticker')}: {e}")
    portfolio = ""
    try:
        portfolio = provider.complete(build_portfolio_prompt(oversold, overbought), max_tokens=900)
    except Exception as e:  # noqa: BLE001
        errors.append(f"portfolio: {e}")
    return {
        "enabled": True,
        "error": "; ".join(errors) if errors else "",
        "per_name": notes,
        "portfolio": portfolio,
        "provider": provider.name,
    }
