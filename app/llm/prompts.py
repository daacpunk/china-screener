"""Shared prompt building blocks.

Single source of truth for the methodology context and per-row line formatting
used by both the Results sidebar synthesis (analysis.py) and the Research Notes
feature (research_notes.py). Keeping these here avoids drift between prompts.
"""
from __future__ import annotations

from typing import Any, Dict


_METHODOLOGY = (
    "METHODOLOGY CONTEXT (do NOT recompute): The RSI(14), MACD, and "
    "volatility-normalized return z-scores were already computed in-app. "
    "Two non-overlapping horizons are used: 1-week (last 5 trading days) and "
    "1-month-ex-last-week (day -21 to -5). By default z is RAW: z = r_horizon/(sigma_daily*sqrt(h)) "
    "(no drift subtraction, so trending names are not pulled to zero). rank_z is the "
    "signed ranking z (default max_abs: the horizon with the larger magnitude, sign preserved); "
    "names are ranked by |rank_z|. peer_relative_z = rank_z - leave-one-out peer median "
    "(GICS sub-industry, rolling up to sector if the sub-industry is thin, else solo); "
    "|peer_relative_z| >= threshold OR a solo group => IDIOSYNCRATIC, else SECTOR/MACRO/POLICY. "
    "Playbooks are scored (reversion_score for longs, fade_score for shorts) with RSI 35/65 bands; "
    "partial_history names (a horizon missing) are excluded from playbooks but kept in master. "
    "Your job is QUALITATIVE synthesis and context — NOT to recalculate signals."
)


def _row_line(r: Dict[str, Any]) -> str:
    def f(x, nd=2):
        try:
            return f"{float(x):.{nd}f}"
        except Exception:
            return "n/a"
    # kind-aware playbook score (reversion for longs, fade for shorts)
    score_bits = ""
    if r.get("reversion_score") is not None:
        score_bits += f" rev_score={f(r.get('reversion_score'))}"
    if r.get("fade_score") is not None:
        score_bits += f" fade_score={f(r.get('fade_score'))}"
    flags = []
    if r.get("partial_history"):
        flags.append("partial_history")
    if r.get("adv_unknown"):
        flags.append("adv_unknown")
    flag_bits = (" flags=" + ",".join(flags)) if flags else ""
    return (
        f"- {r.get('ticker')} ({r.get('name')}) | {r.get('sector')}/{r.get('sub_industry')} "
        f"| 1w z={f(r.get('z_1w'))} 1m-ex-wk z={f(r.get('z_1m_ex_week'))} "
        f"rank_z={f(r.get('rank_z'))} "
        f"| dist20d={f(r.get('dist_from_sma'))} RSI={f(r.get('rsi'),1)} "
        f"MACD={r.get('macd_state')} peer_rel_z={f(r.get('peer_relative_z'))} "
        f"peer_group={r.get('peer_group_used')} peer_n={r.get('peer_count')}"
        f"{score_bits} tag={r.get('dislocation_type')} "
        f"event_flag={r.get('event_flag')}{flag_bits}"
    )
