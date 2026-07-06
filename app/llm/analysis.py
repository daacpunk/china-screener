"""Build prompts from screen rows and run optional LLM synthesis.

Never crashes the screen: if a provider is missing or errors, returns a
structured result with an error note instead.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from .base import LLMProvider
from .prompts import _METHODOLOGY, _row_line
from .resilience import complete_with_fallback


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


def _log_usage_captured(name: str, model: str, section: str, usage: Any,
                        ok: bool, note: str = "") -> None:
    """Log usage from a captured snapshot (name/model/usage). Used by the
    concurrent path: each worker snapshots its answering provider's usage in its
    OWN thread, so reading shared ``last_usage`` here can't race other calls."""
    try:
        from .. import settings_store as ss
        ss.log_usage(name, model or "", section, usage if ok else None, ok=ok, note=note)
    except Exception:
        pass


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
    fallback_providers: Optional[List[LLMProvider]] = None,
) -> Dict[str, Any]:
    """Run the sidebar synthesis. Key-gated and crash-proof.

    Returns dict: {enabled, markdown, error, provider}. With provider=None (no
    key/disabled) returns a clean disabled hint and never raises. The single
    call is routed through retry+fallback so a transient 529 self-recovers.
    """
    if provider is None or not getattr(provider, "available", False):
        return {
            "enabled": False,
            "markdown": "",
            "error": "Set an AI key in Settings to enable synthesis.",
            "provider": None,
        }
    try:
        text, used = complete_with_fallback(
            provider,
            build_sidebar_prompt(oversold, overbought, master),
            fallback_providers=fallback_providers or [],
            section="sidebar",
            max_tokens=max_tokens,
        )
        _log_usage(provider, "sidebar", ok=True)
        return {"enabled": True, "markdown": text or "", "error": "",
                "provider": used or getattr(provider, "name", "")}
    except Exception as e:  # noqa: BLE001
        _log_usage(provider, "sidebar", ok=False, note=str(e)[:200])
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
    max_workers: int = 4,
    fallback_providers: Optional[List[LLMProvider]] = None,
) -> Dict[str, Any]:
    """Run analysis. Returns dict with 'enabled', 'error', 'per_name', 'portfolio'.

    Per-name calls and the portfolio call are dispatched through a bounded
    ThreadPoolExecutor (``max_workers``). Each call goes through
    complete_with_fallback so a transient 529 retries (and falls back to another
    configured provider if the primary stays overloaded). With no
    ``fallback_providers`` the behavior is retry-only (single-provider, but
    resilient). Per-name result ordering stays stable (oversold then overbought)
    by collecting results by index and re-sorting.
    """
    if provider is None or not getattr(provider, "available", False):
        return {
            "enabled": False,
            "error": "No LLM provider/key configured. Add a key in Settings to enable AI analysis.",
            "per_name": [],
            "portfolio": "",
        }
    fallback_providers = fallback_providers or []
    # name -> provider object, so a worker can snapshot the answering provider's
    # usage in its own thread (avoids racing shared last_usage across threads).
    by_name = {getattr(provider, "name", ""): provider}
    for fb in fallback_providers:
        by_name.setdefault(getattr(fb, "name", ""), fb)

    def _capture_usage(used: str) -> Dict[str, Any]:
        p = by_name.get(used, provider)
        return {"name": used or getattr(provider, "name", ""),
                "model": getattr(p, "model", "") or "",
                "usage": getattr(p, "last_usage", None)}

    # Build the per-name task list, preserving order (oversold first).
    tasks: List[Dict[str, Any]] = []
    if per_name:
        for r in oversold[:max_names]:
            tasks.append({"row": r, "playbook": "Oversold-Reversion (long)",
                          "prompt_label": "Oversold-Reversion long"})
        for r in overbought[:max_names]:
            tasks.append({"row": r, "playbook": "Overbought-Fade (short)",
                          "prompt_label": "Overbought-Fade short"})

    def _run_per_name(task: Dict[str, Any]) -> Dict[str, Any]:
        r = task["row"]
        text, used = complete_with_fallback(
            provider,
            build_per_name_prompt(r, task["prompt_label"]),
            fallback_providers=fallback_providers,
            section="per_name",
            max_tokens=300,
        )
        cap = _capture_usage(used)
        note = text or ""
        # Transparency: annotate when a fallback (non-primary) provider answered.
        if used and used != getattr(provider, "name", ""):
            note = f"{note} [via {used}]"
        return {"ticker": r.get("ticker"), "name": r.get("name"),
                "playbook": task["playbook"],
                "note": note, "provider": used, "_usage": cap}

    def _run_portfolio() -> Dict[str, Any]:
        text, used = complete_with_fallback(
            provider,
            build_portfolio_prompt(oversold, overbought),
            fallback_providers=fallback_providers,
            section="portfolio",
            max_tokens=900,
        )
        return {"text": text or "", "provider": used, "_usage": _capture_usage(used)}

    notes: List[Optional[Dict[str, Any]]] = [None] * len(tasks)
    errors: List[str] = []
    portfolio = ""

    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as ex:
        future_to_idx = {ex.submit(_run_per_name, t): i for i, t in enumerate(tasks)}
        portfolio_future = ex.submit(_run_portfolio)

        for fut, idx in future_to_idx.items():
            r = tasks[idx]["row"]
            try:
                res = fut.result()
                cap = res.pop("_usage", {})
                notes[idx] = res
                _log_usage_captured(cap.get("name", ""), cap.get("model", ""), "per_name",
                                    cap.get("usage"), ok=True, note=str(r.get("ticker") or ""))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{r.get('ticker')}: {e}")
                _log_usage(provider, "per_name", ok=False, note=str(e)[:200])

        try:
            pres = portfolio_future.result()
            portfolio = pres["text"]
            cap = pres.get("_usage", {})
            _log_usage_captured(cap.get("name", ""), cap.get("model", ""), "portfolio",
                                cap.get("usage"), ok=True)
        except Exception as e:  # noqa: BLE001
            errors.append(f"portfolio: {e}")
            _log_usage(provider, "portfolio", ok=False, note=str(e)[:200])

    ordered = [n for n in notes if n is not None]
    return {
        "enabled": True,
        "error": "; ".join(errors) if errors else "",
        "per_name": ordered,
        "portfolio": portfolio,
        "provider": provider.name,
    }
