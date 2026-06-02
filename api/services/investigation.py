"""
Investigation / loss-prevention incidents — privacy-preserving.

These detectors flag *behavioural* situations a human should review on the
actual CCTV (potential unbilled exits, unusually long unattended dwell). They
deliberately carry **no identity / biometric data** — only a camera + timestamp
+ a clip reference so a reviewer can pull the secured source footage. A flag is
a *review prompt*, never an accusation.

Each incident dict:
  {
    "kind": str, "severity": "info|warning|critical",
    "camera": str, "ts": ISO,            # where + when to look
    "window": {"from": ISO, "to": ISO},  # the span to scrub
    "evidence": str,
    "clip_ref": {"camera", "from", "to", "review"}  # how to pull footage
  }

Registry pattern (mirrors anomaly_detect): add a detector class + append to
INCIDENT_DETECTORS; the route never changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Protocol

IST = timezone(timedelta(hours=5, minutes=30))
BUCKET_MS = 5 * 60 * 1000
CLIP_PAD_S = 15  # seconds of context around an incident for the review clip


def _ms(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return int(dt.timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=IST).isoformat()


def _clip_ref(camera: str, center_ms: int, pad_s: int = CLIP_PAD_S) -> dict:
    lo, hi = center_ms - pad_s * 1000, center_ms + pad_s * 1000
    return {
        "camera": camera,
        "from": _iso(lo),
        "to": _iso(hi),
        "review": f"Open {camera} footage {_iso(lo)[11:19]}–{_iso(hi)[11:19]} (±{pad_s}s)",
    }


class Window:
    def __init__(self, from_: Optional[str], to: Optional[str]):
        self.from_ = from_
        self.to = to


class IncidentDetector(Protocol):
    kind: str

    def run(self, store, pos, window: Window) -> List[dict]:
        ...


# ---------------------------------------------------------------------------
# 1) Unbilled cash approach — people at the till not matched by POS bills
# ---------------------------------------------------------------------------


class UnbilledCashApproachDetector:
    """
    Per 5-min bucket: count cash-counter approaches (CAM 5) vs POS bills. If
    approaches exceed bills, some people stood at the till without a recorded
    sale — a review prompt for unbilled exits / manual-discount abuse.
    """

    kind = "unbilled_cash_approach"

    def run(self, store, pos, window: Window) -> List[dict]:
        approaches = store.get_events(
            window.from_, window.to, type_="visit.approached_cash", limit=100000)
        if not approaches:
            return []

        # group approach timestamps per 5-min bucket (keep earliest for the clip)
        by_bucket: Dict[int, List[int]] = {}
        cam_by_bucket: Dict[int, str] = {}
        for e in approaches:
            ms = _ms(e["ts"])
            b = ms // BUCKET_MS
            by_bucket.setdefault(b, []).append(ms)
            cam_by_bucket[b] = e.get("camera") or "cam5"

        bills_by_bucket: Dict[int, int] = {}
        for bill in pos.get_bills(window.from_, window.to):
            if bill.ts_ms is not None:
                bills_by_bucket[bill.ts_ms // BUCKET_MS] = (
                    bills_by_bucket.get(bill.ts_ms // BUCKET_MS, 0) + 1)

        out: List[dict] = []
        for b, stamps in sorted(by_bucket.items()):
            n_app = len(stamps)
            n_bill = bills_by_bucket.get(b, 0)
            unmatched = n_app - n_bill
            if unmatched <= 0:
                continue
            camera = cam_by_bucket[b]
            center = min(stamps)
            severity = "critical" if unmatched >= 3 else "warning"
            out.append({
                "kind": self.kind,
                "severity": severity,
                "camera": camera,
                "ts": _iso(center),
                "window": {"from": _iso(b * BUCKET_MS), "to": _iso((b + 1) * BUCKET_MS)},
                "evidence": (
                    f"{n_app} cash-counter approach(es) but only {n_bill} POS bill(s) "
                    f"in this 5-min window — {unmatched} unmatched. Review for unbilled exits."
                ),
                "clip_ref": _clip_ref(camera, center),
            })
        return out


# ---------------------------------------------------------------------------
# 2) Long unattended dwell — customer lingering well beyond normal
# ---------------------------------------------------------------------------


class LongDwellDetector:
    """
    A customer (staff excluded) whose dwell is far above the per-camera norm —
    a loss-prevention review prompt (concealment, tag-tampering). Uses the same
    visit.ended dwell the funnel uses; staff visits are filtered out.
    """

    kind = "long_unattended_dwell"
    DWELL_FLOOR_MS = 60_000  # >= 60s is notable on these short clips

    def run(self, store, pos, window: Window) -> List[dict]:
        staff = getattr(store, "staff_visit_ids", set())
        visits = store.get_events(window.from_, window.to, type_="visit.ended", limit=100000)
        out: List[dict] = []
        for e in visits:
            p = e["payload"]
            if p.get("visit_id") in staff:
                continue
            dwell = p.get("total_dwell_ms", 0)
            if dwell < self.DWELL_FLOOR_MS:
                continue
            camera = e.get("camera") or "?"
            end_ms = _ms(e["ts"])
            zones = ", ".join(p.get("zones_visited", [])) or "—"
            out.append({
                "kind": self.kind,
                "severity": "info",
                "camera": camera,
                "ts": e["ts"],
                "window": {"from": _iso(end_ms - dwell), "to": e["ts"]},
                "evidence": (
                    f"Customer dwelled {dwell / 1000:.0f}s (zones: {zones}) — "
                    f"well above normal. Review for concealment / tampering."
                ),
                "clip_ref": _clip_ref(camera, end_ms),
            })
        return out


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

INCIDENT_DETECTORS: List[IncidentDetector] = [
    UnbilledCashApproachDetector(),
    LongDwellDetector(),
]

_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def find_incidents(
    store, pos, from_: Optional[str], to: Optional[str],
    kinds: Optional[List[str]] = None,
) -> List[dict]:
    window = Window(from_, to)
    out: List[dict] = []
    for det in INCIDENT_DETECTORS:
        if kinds and det.kind not in kinds:
            continue
        out.extend(det.run(store, pos, window))
    out.sort(key=lambda i: (_SEVERITY_RANK.get(i["severity"], 9), i["ts"]))
    return out
