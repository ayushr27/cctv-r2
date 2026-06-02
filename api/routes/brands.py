"""GET /brands?from=&to= — brand-stand engagement (attention -> sales).

Per physical brand stand: customer attention (dwell, visits, attention share)
joined to POS outcome (revenue, units, top products sold) plus derived
efficiency signals. Aggregate and identity-free — no per-customer profiling.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from services.brands import brand_engagement
from services.event_store import store
from services.pos_join import pos
from services.window import resolve_window

router = APIRouter()


@router.get("/brands")
def get_brands(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    win_from, win_to = resolve_window(from_, to)
    stands = brand_engagement(store, pos, win_from, win_to)
    return {
        "window": {"from": win_from, "to": win_to},
        "count": len(stands),
        "stands": stands,
        "note": (
            "Attention = customer dwell at the stand (staff excluded); top_products "
            "is aggregate POS sales for the stand's brands (what sells), NOT linked "
            "to any individual. No per-customer preference or identity is stored."
        ),
    }
