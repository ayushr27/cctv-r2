"""GET /customers?from=&to= — non-demographic customer segments.

Solo vs group shoppers (CV), unique vs repeat customers (POS), and basket
composition. No gender/age inference — see services/customers.py.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from services.customers import customer_segments
from services.event_store import store
from services.pos_join import pos
from services.window import resolve_window

router = APIRouter()


@router.get("/customers")
def get_customers(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    win_from, win_to = resolve_window(from_, to)
    segments = customer_segments(store, pos, win_from, win_to)
    return {"window": {"from": win_from, "to": win_to}, **segments}
