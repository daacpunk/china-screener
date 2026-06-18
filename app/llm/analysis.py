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
