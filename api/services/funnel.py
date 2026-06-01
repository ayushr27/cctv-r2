"""
Funnel computation service.

Builds the 5-stage retail funnel for a time window:

    footfall  -> browsed -> engaged -> approached_cash -> billed

Multi-camera honesty note
-------------------------
Because there is no cross-camera identity (deliberate — see CHOICES.md), the
stages are NOT a single chained per-customer journey. Each stage is an
independent count within the window, drawn from the camera that owns it:

  footfall        unique visit.entered visit_ids        (cam3, entrance)
  browsed         visits with a zone dwell > 5s          (cam1/cam2, interior)
  engaged         visits that touched >= 2 zones         (cam1/cam2)
  approached_cash visits with visit.approached_cash      (cam5, billing)
  billed          bill count in window                   (POS CSV)

This is the same time-bucket philosophy as the POS join. Counts can therefore
be non-monotonic across cameras (e.g. interior browse > entrance footfall when
the entrance camera under-counts); we clamp the reported funnel to be
monotonically non-increasing so the shape stays sensible, and expose the raw
per-stage counts alongside for transparency.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from services.event_store import store
from services.pos_join import pos

STAGE_NAMES = ["footfall", "browsed", "engaged", "approached_cash", "billed"]
BROWSE_DWELL_MS = 5000


def _raw_stage_counts(from_: Optional[str], to_: Optional[str]) -> Dict[str, int]:
    # Staff visits (track.staff_classified) are excluded from every CV stage —
    # the funnel measures customers, not employees.
    staff = store.staff_visit_ids

    # footfall: unique customer visit_ids that crossed an entry line
    entered = store.get_payloads("visit.entered", from_, to_)
    footfall = len({p["visit_id"] for p in entered if p["visit_id"] not in staff})

    # browsed: visit_ids with at least one zone dwell > 5s
    exited = store.get_payloads("visit.exited_zone", from_, to_)
    browsed_visits = {
        p["visit_id"] for p in exited
        if p.get("dwell_ms", 0) > BROWSE_DWELL_MS and p["visit_id"] not in staff
    }
    browsed = len(browsed_visits)

    # engaged: visit_ids that visited >= 2 distinct zones (from visit.ended)
    visits = store.get_visits(from_, to_)
    engaged = sum(
        1 for v in visits
        if len(v.get("zones_visited", [])) >= 2 and v.get("visit_id") not in staff
    )

    # approached_cash: unique customer visit_ids with a cash approach
    cash = store.get_payloads("visit.approached_cash", from_, to_)
    approached_cash = len({p["visit_id"] for p in cash if p["visit_id"] not in staff})

    # billed: bills in window
    billed = len(pos.get_bills(from_, to_))

    return {
        "footfall": footfall,
        "browsed": browsed,
        "engaged": engaged,
        "approached_cash": approached_cash,
        "billed": billed,
    }


def _monotonic(raw: Dict[str, int]) -> List[int]:
    """
    Clamp the CV-derived stages (footfall..approached_cash) to be monotonically
    non-increasing so the funnel never widens. ``billed`` is POS-sourced and
    independent of CV footfall — it is reported at its TRUE count, never clamped
    to zero just because the (short-sample) CV footfall was low in this window.
    Clamping billed to footfall would silently hide real revenue.
    """
    cv_stages = STAGE_NAMES[:-1]  # footfall, browsed, engaged, approached_cash
    out, prev = [], None
    for name in cv_stages:
        v = raw[name]
        if prev is not None:
            v = min(v, prev)
        out.append(v)
        prev = v
    out.append(raw["billed"])  # un-clamped
    return out


def compute_funnel(from_: Optional[str] = None, to_: Optional[str] = None) -> dict:
    raw = _raw_stage_counts(from_, to_)
    clamped = _monotonic(raw)

    stages = [{"name": n, "count": c} for n, c in zip(STAGE_NAMES, clamped)]

    drop_off_rates = []
    for i in range(len(clamped) - 1):
        prev = clamped[i]
        drop = (prev - clamped[i + 1]) / prev if prev else 0.0
        drop_off_rates.append(round(drop, 3))

    return {
        "stages": stages,
        "drop_off_rates": drop_off_rates,
        "raw_counts": raw,  # un-clamped, for transparency
    }
