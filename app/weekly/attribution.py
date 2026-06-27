r"""Phase D-2 weekly sector-vs-stock-specific attribution — PURE, NaN-safe.

For each notable mover we decompose its 1-week return into a peer (sector)
component and a name-specific residual, REUSING the exact peer-grouping algorithm
from ``app.screen_engine`` (Step 3): a leave-one-out peer MEDIAN that EXCLUDES
the name itself, a sub_industry -> sector roll-up when a group has fewer than
``min_peers`` OTHER names, and an idiosyncratic-solo tag when even the sector has
no peers.

This module intentionally re-implements that small leave-one-out routine rather
than importing from ``screen_engine`` so the MSCI screen's behavior and tests are
not perturbed (the two operate on different inputs: screen_engine nets ranking
z-scores; here we net raw 1W returns). The grouping/exclusion math is identical:

    peer_median = median( group_returns \ {self} )
    residual    = name_1w_return - peer_median
    peer_count  = number of OTHER names in the chosen group

Attribution tag (defaults overridable via a PARAMS-style dict):
    * "Stock-specific" when |residual| is large:
          |residual| > max(fixed_band_pp, k * peer_dispersion)
      where peer_dispersion = stdev of the peer (leave-one-out) 1W returns.
    * "Sector-driven" when |residual| is within the band AND the sector itself
      moved materially (|peer_median| >= sector_move_pp).
    * "Mixed" otherwise (small residual but a quiet sector).
    * idiosyncratic-solo names (no peers at all) are tagged "Stock-specific"
      with peer_group_used="idiosyncratic-solo" (nothing to net against).

All thresholds are in PERCENTAGE POINTS (e.g. 5.0 == 5pp == 0.05 in return
space). Returns are passed in as fractions (0.05 == +5%) and converted
internally. Never raises; missing inputs yield None fields.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Optional

# Default attribution bands (percentage points). Overridable via a params dict.
PARAMS: Dict[str, float] = {
    "min_peers": 3,        # minimum OTHER names to use a peer group (matches screen_engine)
    "fixed_band_pp": 5.0,  # residual must exceed this many pp to be stock-specific
    "k": 1.5,              # ...or this multiple of peer dispersion
    "sector_move_pp": 2.0,  # the sector itself must move >= this (pp) for "Sector-driven"
}

SOLO = "idiosyncratic-solo"


def _f(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _norm_group(v: Any) -> Optional[str]:
    """Normalize a sub_industry / sector label; blanks / NA -> None."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "n/a", "#n/a"):
        return None
    return s


def build_groups(
    rows: List[Dict[str, Any]],
) -> Dict[str, Dict[str, List[float]]]:
    """Index 1W returns by sub_industry and by sector for leave-one-out lookups.

    ``rows`` is a list of {symbol, ret_1w, sub_industry, sector}. Returns
    {"sub": {label: [(symbol, ret)...]}, "sec": {...}} where each entry keeps the
    symbol so the self-exclusion is exact (not value-based).
    """
    by_sub: Dict[str, List[tuple]] = {}
    by_sec: Dict[str, List[tuple]] = {}
    for r in rows:
        sym = r.get("symbol")
        ret = _f(r.get("ret_1w"))
        if sym is None or ret is None:
            continue
        sub = _norm_group(r.get("sub_industry"))
        sec = _norm_group(r.get("sector"))
        if sub is not None:
            by_sub.setdefault(sub, []).append((sym, ret))
        if sec is not None:
            by_sec.setdefault(sec, []).append((sym, ret))
    return {"sub": by_sub, "sec": by_sec}


def _peers_excluding_self(group: List[tuple], symbol: Any) -> List[float]:
    """Leave-one-out: every OTHER name's return in the group (excludes ``symbol``
    once). Mirrors screen_engine's ``series.drop(idx)`` self-exclusion."""
    out: List[float] = []
    dropped = False
    for sym, ret in group:
        if not dropped and sym == symbol:
            dropped = True
            continue
        out.append(ret)
    return out


def attribute_one(
    row: Dict[str, Any],
    groups: Dict[str, Dict[str, List[tuple]]],
    params: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Attribute one name's 1W move to sector vs stock-specific. Never raises.

    Returns: {attribution, peer_group_used, peer_count, peer_median_1w,
              residual_1w}. All return-space figures are FRACTIONS (matching the
    rest of metrics); bands are configured in percentage points.
    """
    p = {**PARAMS, **(params or {})}
    min_peers = int(p["min_peers"])
    fixed_band = float(p["fixed_band_pp"]) / 100.0
    k = float(p["k"])
    sector_move = float(p["sector_move_pp"]) / 100.0

    out: Dict[str, Any] = {
        "attribution": None,
        "peer_group_used": SOLO,
        "peer_count": 0,
        "peer_median_1w": None,
        "residual_1w": None,
    }
    sym = row.get("symbol")
    ret = _f(row.get("ret_1w"))
    if sym is None or ret is None:
        return out

    sub = _norm_group(row.get("sub_industry"))
    sec = _norm_group(row.get("sector"))

    # sub_industry leave-one-out first; roll up to sector when too few OTHERS.
    peers: List[float] = []
    group_used = SOLO
    if sub is not None:
        cand = _peers_excluding_self(groups["sub"].get(sub, []), sym)
        if len(cand) >= min_peers:
            peers = cand
            group_used = "sub_industry"
    if group_used == SOLO and sec is not None:
        cand = _peers_excluding_self(groups["sec"].get(sec, []), sym)
        if len(cand) >= min_peers:
            peers = cand
            group_used = "sector"

    if group_used == SOLO or not peers:
        # Nothing to net against -> idiosyncratic-solo, treated stock-specific.
        out["attribution"] = "Stock-specific"
        out["peer_group_used"] = SOLO
        out["peer_count"] = 0
        out["peer_median_1w"] = None
        out["residual_1w"] = None
        return out

    peer_median = statistics.median(peers)
    dispersion = statistics.pstdev(peers) if len(peers) >= 2 else 0.0
    residual = ret - peer_median

    band = max(fixed_band, k * dispersion)
    if abs(residual) > band:
        tag = "Stock-specific"
    elif abs(peer_median) >= sector_move:
        tag = "Sector-driven"
    else:
        tag = "Mixed"

    out["attribution"] = tag
    out["peer_group_used"] = group_used
    out["peer_count"] = len(peers)
    out["peer_median_1w"] = float(peer_median)
    out["residual_1w"] = float(residual)
    return out


def attribute_movers(
    rows: List[Dict[str, Any]],
    symbols: List[str],
    params: Optional[Dict[str, float]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Compute attribution for a set of ``symbols`` against the full ``rows``
    universe (so peer groups are formed from EVERY name, not just the movers).

    ``rows``: list of {symbol, ret_1w, sub_industry, sector} for the whole
    universe. Returns {symbol: attribution_dict}. Never raises.
    """
    try:
        groups = build_groups(rows)
        by_sym = {r.get("symbol"): r for r in rows}
        out: Dict[str, Dict[str, Any]] = {}
        for sym in symbols:
            row = by_sym.get(sym)
            if row is None:
                continue
            out[sym] = attribute_one(row, groups, params)
        return out
    except Exception:  # noqa: BLE001 — pure module must never raise
        return {}
