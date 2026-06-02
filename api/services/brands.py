"""
Brand-stand engagement analytics.

Combines CV *attention* (customer dwell at a brand stand, from zone events with
staff excluded) with POS *outcome* (revenue, units, top products for that
stand's brands) to answer "how much attention does each brand stand draw, and
how well does that attention convert to sales".

Unit of analysis is the STAND (a physical zone covering a brand cluster), named
after its anchor brand — not an individual brand or an individual customer.
Everything here is aggregate and identity-free:
  * attention is zone dwell, not "who" dwelled;
  * top_products is what SELLS from the brand (POS), not what a person "likes".

Derived signals:
  attention_share          this stand's share of total customer dwell
  revenue_per_visit        rupees of sales (its brands) / stand visits
  revenue_per_attn_min     rupees of sales / minutes of customer attention
  signal                   plain-language read (e.g. "browsed, low conversion")
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Optional

_ZONE_BRANDS_PATH = os.path.join(os.path.dirname(__file__), "..", "zone_brands.json")
try:
    with open(_ZONE_BRANDS_PATH) as f:
        _ZONE_BRANDS = json.load(f).get("zones", {})
except FileNotFoundError:
    _ZONE_BRANDS = {}

# Below this revenue-per-visit a heavily-browsed stand is flagged as a
# conversion opportunity (rupees; heuristic, aggregate).
LOW_CONVERSION_RPV = 200.0
HIGH_ATTENTION_SHARE = 0.25


def _signal(attention_share: float, revenue: float, visits: int) -> str:
    """A plain-language merchandising read for the stand (aggregate, heuristic)."""
    if visits == 0 and revenue == 0:
        return "no activity in window"
    if visits == 0:
        return "sales without detected footfall (short CV sample)"
    if revenue == 0:
        return "browsed but no sales — merchandising opportunity"
    if attention_share >= HIGH_ATTENTION_SHARE and revenue / visits < LOW_CONVERSION_RPV:
        return "high interest, low conversion — review pricing/placement"
    return "converting attention to sales"


def brand_engagement(
    store, pos, from_: Optional[str] = None, to: Optional[str] = None
) -> list[dict]:
    staff = getattr(store, "staff_visit_ids", set())

    entered = store.get_payloads("visit.entered_zone", from_, to)
    exited = store.get_payloads("visit.exited_zone", from_, to)

    visits_by_zone: dict[str, set] = defaultdict(set)
    for p in entered:
        if p.get("visit_id") not in staff:
            visits_by_zone[p["zone"]].add(p["visit_id"])

    dwell_by_zone: dict[str, int] = defaultdict(int)
    for p in exited:
        if p.get("visit_id") not in staff:
            dwell_by_zone[p["zone"]] += p.get("dwell_ms", 0)

    total_dwell_ms = sum(dwell_by_zone.values()) or 1
    breakdown = pos.brand_breakdown_in_window(from_, to)

    stands = []
    names = set(visits_by_zone) | set(dwell_by_zone) | set(_ZONE_BRANDS)
    for name in sorted(names):
        meta = _ZONE_BRANDS.get(name, {})
        brands = meta.get("brands", [])
        visits = len(visits_by_zone.get(name, set()))
        dwell_ms = dwell_by_zone.get(name, 0)
        attn_min = dwell_ms / 60000

        revenue = round(sum(breakdown.get(b, {}).get("revenue", 0.0) for b in brands), 2)
        units = sum(breakdown.get(b, {}).get("units", 0) for b in brands)
        # merge top products across the stand's brands
        prod: dict = defaultdict(int)
        for b in brands:
            for prod_name, q in breakdown.get(b, {}).get("top_products", []):
                prod[prod_name] += q
        top_products = sorted(prod.items(), key=lambda x: -x[1])[:3]

        attention_share = round(dwell_ms / total_dwell_ms, 3)
        stands.append({
            "stand": name,
            "camera": meta.get("camera"),
            "brands": brands,
            "visits": visits,
            "attention_seconds": round(dwell_ms / 1000, 1),
            "attention_share": attention_share,
            "revenue": revenue,
            "units": units,
            "revenue_per_visit": round(revenue / visits, 2) if visits else 0.0,
            "revenue_per_attention_min": round(revenue / attn_min, 2) if attn_min else 0.0,
            "top_products": [{"product": n, "units": q} for n, q in top_products],
            "signal": _signal(attention_share, revenue, visits),
        })

    # rank by attention (most-looked-at stand first)
    stands.sort(key=lambda s: -s["attention_seconds"])
    return stands
