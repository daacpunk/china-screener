"""Phase D-3 Wave 2 (#5): hit-rate scorecard — measurement ONLY.

A precursor to Phase B's learning loop. This module reads the metrics that are
ALREADY persisted with each weekly note (``weekly_notes.metrics_json``) and
asks a simple, honest question: of the extreme dislocations we FLAGGED in prior
weekly notes, how many have since begun MEAN-REVERTING (moved opposite to the
flagged move) by a meaningful fraction of the flagged move?

EXPLICIT non-goals (deferred to Phase B, NOT built here): no playbook writing,
no prompt-injected "lessons", no council, no schema changes. Pure measurement +
display, reading the metrics_json that is already stored.

Everything here is PURE and defensive: missing data yields ``None`` / an
"insufficient history" string, and no function ever raises.

LOCKED definitions:
  * Evaluate up to 8 prior weekly notes (``window_weeks`` default 8).
  * A dislocation is a MEAN-REVERSION candidate: the flagged 1W move is
    ``flag_ret`` and the EXPECTED subsequent move is OPPOSITE in sign.
  * Realized move (``since_ret``) is measured from the prior note's as-of date
    (the nearest current-snapshot trading day ON/AFTER that as-of) to the LATEST
    close in the current snapshot: ``since_ret = end/start - 1``.
  * A "hit" = ``sign(since_ret)`` is OPPOSITE to ``sign(flag_ret)`` AND
    ``abs(since_ret) >= hit_fraction * abs(flag_ret)`` (``hit_fraction`` 0.25).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import note_store


# ---------------------------------------------------------------------------
# Loading prior notes' persisted metrics
# ---------------------------------------------------------------------------
def load_prior_note_metrics(
    limit: int = 8,
    exclude_asof: Any = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load up to ``limit`` prior weekly notes' persisted metrics, most-recent
    first.

    Reads ``note_store.list_notes(limit=limit+2)`` (a small over-fetch so that
    excluding the current run's as-of and skipping metric-less rows still leaves
    room), then ``get_note`` for each to hydrate the parsed ``metrics``. Returns
    a list of ``{"asof", "metrics"}`` dicts, most-recent first, capped at
    ``limit``.

      * ``exclude_asof`` — when given, any note whose ``asof`` equals it (string
        compare) is skipped (so the current run's own just-saved note, if any,
        is not evaluated against itself).
      * Notes with empty / missing metrics are skipped.

    Never raises — returns [] on any error.
    """
    out: List[Dict[str, Any]] = []
    try:
        lim = max(1, int(limit))
    except (TypeError, ValueError):
        lim = 8
    ex = None if exclude_asof is None else str(exclude_asof)
    try:
        listed = note_store.list_notes(limit=lim + 2, db_path=db_path)
    except Exception:  # noqa: BLE001 — reads must never break note generation
        return out
    for row in listed or []:
        try:
            nid = row.get("id")
            if nid is None:
                continue
            rec = note_store.get_note(int(nid), db_path=db_path)
        except Exception:  # noqa: BLE001
            continue
        if not rec:
            continue
        asof = rec.get("asof")
        if ex is not None and asof is not None and str(asof) == ex:
            continue
        metrics = rec.get("metrics") or {}
        if not metrics:
            continue
        out.append({"asof": asof, "metrics": metrics})
        if len(out) >= lim:
            break
    return out


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _sign(x: Optional[float]) -> int:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def _flagged_items(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Collect the flagged dislocation items from a prior note's metrics.

    Reads ``metrics["opportunities"]["dislocations"]`` (each item has a symbol
    and its ``ret_1w`` at flag time) plus, when present, the "stretched to
    extremes" list under ``metrics["movers"]["extremes"]`` (also mean-reversion
    candidates). Returns a de-duplicated list of ``{"symbol", "flag_ret"}`` with
    a valid symbol and a finite, non-zero ``flag_ret``. Never raises.
    """
    out: List[Dict[str, Any]] = []
    seen: set = set()
    if not isinstance(metrics, dict):
        return out

    def _add(sym: Any, flag_ret: Any) -> None:
        try:
            s = str(sym).strip()
        except Exception:  # noqa: BLE001
            return
        if not s or s in seen:
            return
        try:
            fr = float(flag_ret)
        except (TypeError, ValueError):
            return
        if fr != fr or fr == 0:  # NaN or zero -> no direction to test
            return
        seen.add(s)
        out.append({"symbol": s, "flag_ret": fr})

    opps = metrics.get("opportunities") or {}
    for it in (opps.get("dislocations") or []):
        if isinstance(it, dict):
            _add(it.get("symbol"), it.get("ret_1w"))
    # Extremes (mean-reversion watchlist), when present.
    movers = metrics.get("movers") or {}
    for it in (movers.get("extremes") or []):
        if isinstance(it, dict):
            _add(it.get("symbol"), it.get("ret_1w"))
    return out


def _realized_since(series: Any, asof: Any) -> Optional[float]:
    """Realized simple return from the nearest close ON/AFTER ``asof`` to the
    latest close in the current chronological ``series`` (a list of
    ``{"date","close"}``). Returns None when the name lacks usable data or when
    there is no trading day on/after ``asof``. Never raises.
    """
    try:
        if not series or asof is None:
            return None
        import pandas as pd

        df = pd.DataFrame(series)
        if "date" not in df.columns or "close" not in df.columns:
            return None
        dt = pd.to_datetime(df["date"], errors="coerce")
        close = pd.to_numeric(df["close"], errors="coerce")
        s = pd.Series(close.values, index=dt).dropna()
        s = s[~s.index.isna()].sort_index()
        if s.shape[0] < 1:
            return None
        anchor = pd.to_datetime(asof, errors="coerce")
        if anchor is pd.NaT or (isinstance(anchor, float) and anchor != anchor):
            return None
        on_after = s[s.index >= anchor]
        if on_after.shape[0] < 1:
            return None
        start = float(on_after.iloc[0])
        end = float(s.iloc[-1])
        if start == 0 or start != start or end != end:
            return None
        return end / start - 1.0
    except Exception:  # noqa: BLE001 — pure; never raise
        return None


# ---------------------------------------------------------------------------
# The hit-rate scorecard
# ---------------------------------------------------------------------------
_INSUFFICIENT = ("Insufficient history - need >= 1 prior weekly note with "
                 "flagged dislocations.")


def _definition(window_weeks: int, hit_fraction: float) -> str:
    return (
        f"Of the extreme dislocations flagged in the past {window_weeks} weekly "
        "notes, a 'hit' means the name has since moved OPPOSITE to the flagged "
        f"1W move (mean-reversion) by at least {int(round(hit_fraction * 100))}% "
        "of that flagged move, measured from the prior note's as-of date to the "
        "current snapshot's latest close."
    )


def evaluate_hit_rate(
    prior_notes: List[Dict[str, Any]],
    current_tickers_series: Dict[str, Any],
    current_asof: Any = None,
    window_weeks: int = 8,
    hit_fraction: float = 0.25,
) -> Dict[str, Any]:
    """Score how prior flagged dislocations have played out (#5). NEVER raises.

    ``prior_notes`` is the list from ``load_prior_note_metrics`` (each
    ``{"asof", "metrics"}``), most-recent first. ``current_tickers_series`` maps
    ticker -> chronological ``[{"date","close"}, ...]`` from the CURRENT
    snapshot, so realized moves can be measured from a prior as-of date to now.

    For each of the most-recent ``window_weeks`` prior notes, each flagged name's
    realized move (``since_ret``) is measured from the nearest current-snapshot
    trading day ON/AFTER the prior note's as-of to the latest close. A name is
    scored a hit when its realized move is OPPOSITE in sign to the flagged move
    AND at least ``hit_fraction`` of the flagged move's magnitude. Names not in
    the current series (or lacking data) are unevaluable and skipped.

    Returns::

        {
          "evaluated": [{symbol, flagged_on, flag_ret, since_ret, hit}, ...],
          "n_hits": int, "n_evaluated": int,
          "window_weeks": int, "hit_fraction": float,
          "definition": <human-readable rule>,
          "summary": <e.g. "3 of 4 extreme dislocations flagged in the past 8
                      weeks have begun mean-reverting"> | insufficient message,
        }
    """
    try:
        ww = max(1, int(window_weeks))
    except (TypeError, ValueError):
        ww = 8
    try:
        hf = float(hit_fraction)
        if hf != hf or hf < 0:
            hf = 0.25
    except (TypeError, ValueError):
        hf = 0.25

    definition = _definition(ww, hf)
    base = {
        "evaluated": [],
        "n_hits": 0,
        "n_evaluated": 0,
        "window_weeks": ww,
        "hit_fraction": hf,
        "definition": definition,
        "summary": _INSUFFICIENT,
    }

    prior_notes = prior_notes or []
    current_tickers_series = current_tickers_series or {}
    if not prior_notes or not current_tickers_series:
        return base

    evaluated: List[Dict[str, Any]] = []
    seen_syms: set = set()  # first (most-recent) flag per symbol wins
    n_hits = 0

    for note in prior_notes[:ww]:
        if not isinstance(note, dict):
            continue
        asof = note.get("asof")
        metrics = note.get("metrics") or {}
        for item in _flagged_items(metrics):
            sym = item["symbol"]
            if sym in seen_syms:
                continue
            flag_ret = item["flag_ret"]
            series = current_tickers_series.get(sym)
            if series is None:
                # Try a bare-code match (e.g. '9988' vs '9988-HK') defensively.
                continue
            since_ret = _realized_since(series, asof)
            if since_ret is None:
                continue  # unevaluable
            seen_syms.add(sym)
            hit = bool(
                _sign(since_ret) != 0
                and _sign(since_ret) == -_sign(flag_ret)
                and abs(since_ret) >= hf * abs(flag_ret)
            )
            if hit:
                n_hits += 1
            evaluated.append({
                "symbol": sym,
                "flagged_on": asof,
                "flag_ret": flag_ret,
                "since_ret": since_ret,
                "hit": hit,
            })

    n_eval = len(evaluated)
    if n_eval == 0:
        return base

    # Most salient first: largest flagged magnitude on top.
    evaluated.sort(key=lambda e: abs(e.get("flag_ret") or 0.0), reverse=True)
    summary = (
        f"{n_hits} of {n_eval} extreme dislocation"
        f"{'s' if n_eval != 1 else ''} flagged in the past {ww} weeks have "
        "begun mean-reverting (moved opposite the flagged dislocation by at "
        f"least {int(round(hf * 100))}% of the flagged move)."
    )
    return {
        "evaluated": evaluated,
        "n_hits": int(n_hits),
        "n_evaluated": int(n_eval),
        "window_weeks": ww,
        "hit_fraction": hf,
        "definition": definition,
        "summary": summary,
    }
