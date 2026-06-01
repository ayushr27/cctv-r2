"""
Default time-window resolution.

The CCTV clips are short samples (~3 min) while the POS CSV spans the full
trading day. When a caller gives no from/to, we default to the UNION of the
event range and the POS range, so the dashboard shows all available data
(footfall from the clips + every bill) rather than a 3-minute slice that would
read billed=0.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from services.event_store import store
from services.pos_join import pos

IST = timezone(timedelta(hours=5, minutes=30))


def _ms(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return int(dt.timestamp() * 1000)


def resolve_window(from_: Optional[str], to: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (from_, to) filled in with the union of event + POS ranges when the
    caller leaves them blank. Explicit caller values always win.
    """
    ev_lo, ev_hi = store.data_range()
    pos_lo, pos_hi = pos.data_range()

    lows = [x for x in (ev_lo, pos_lo) if x]
    highs = [x for x in (ev_hi, pos_hi) if x]

    default_from = min(lows, key=lambda s: _ms(s)) if lows else None
    default_to = max(highs, key=lambda s: _ms(s)) if highs else None

    return (from_ or default_from, to or default_to)
