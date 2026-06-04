"""
Behavioral staff classification — a post-processing pass over events.jsonl.

It reads completed visits, scores each on behavioral signals, and appends a
``track.staff_classified`` event for every visit judged to be a staff member.
The output is written to a new file; the original event log is untouched, so
classification can be re-run with different thresholds without re-detecting.

Heuristic (>= 2 of 3 signals => staff), per the plan's structure
----------------------------------------------------------------
  1. long_dwell    total_dwell_ms above a threshold
  2. multi_zone    zones_count >= --zones-min
  3. cash_anchor   cash_passes >= 1 AND long_dwell (lingers AT the till, i.e.
                   an operator, vs a customer who just steps up to pay)

CLIP-LENGTH ADAPTATION (important — read this)
----------------------------------------------
The plan specifies absolute thresholds tuned for a full day of footage:
dwell > 30 min, zones >= 3, cash_passes >= 2. Those CANNOT fire on the ~2-minute
sample clips that are the only footage available: max observed dwell is ~140s,
each camera only covers 2-3 zones, and events.py emits approached_cash at most
once per visit. Applied verbatim they classify ZERO staff and fail the
acceptance check.

So the dwell threshold is CLIP-RELATIVE: a visit is "long dwell" if it dwells
longer than ``--dwell-floor-s`` (absolute) OR longer than ``--dwell-median-mult``
times the per-camera median dwell. On these clips that surfaces exactly the
people who stand at a counter for most of the clip — the salespeople. Every
threshold is a CLI flag, so the same code runs verbatim on full-day footage by
passing --dwell-floor-s 1800 --zones-min 3 etc.

Failure modes
-------------
  * False positive: a slow shopper who lingers a long time in one spot reads as
    long_dwell; needs a second signal (zone/cash) to be classified, which
    mitigates but does not eliminate this.
  * False negative: a dedicated cash-counter operator who never leaves one zone
    only trips long_dwell + cash_anchor (still 2 signals — caught), but a
    roaming stock clerk who moves fast may trip none.
  * Mitigation (future work): a face-embedding bank built from a calibration
    pass over the first hour of footage would identify staff directly rather
    than inferring from behavior.
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from typing import Dict, List, Optional

import structlog

try:
    from store_config import classifier_config
except Exception:  # pragma: no cover - keeps standalone legacy invocations working
    classifier_config = None

from schemas import (
    StaffEvidence,
    TrackStaffClassified,
    TrackStaffClassifiedPayload,
    dump_jsonl,
    load_jsonl,
)

logger = structlog.get_logger()

# Defaults tuned for the ~2-min sample clips. Override for longer footage.
DEFAULT_DWELL_FLOOR_S = 40.0      # absolute "long dwell" floor (seconds)
DEFAULT_DWELL_MEDIAN_MULT = 4.0   # OR > this * per-camera median dwell
DEFAULT_ZONES_MIN = 2             # multi-zone signal (clips have <=3 zones/cam)
DEFAULT_MIN_SIGNALS = 2           # >= this many signals => staff
# Strict: on this dim evening footage most clothing reads somewhat dark, so the
# black-outfit bar is high (validated against the darkness distribution — 0.85
# isolates ~5 all-black staff vs 46 at 0.5). Lower it for brighter footage.
DEFAULT_DARK_THRESHOLD = 0.85     # median top&bot black-fraction >= this => black outfit
DEFAULT_UNIFORM_RULE = "top_and_bottom"
DEFAULT_UNIFORM_MIN_DWELL_S = 0.0


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


class VisitAgg:
    __slots__ = ("visit_id", "track_id", "camera", "ts", "total_dwell_ms",
                 "zones_count", "cash_passes", "dark_top", "dark_bot")

    def __init__(self, visit_id):
        self.visit_id = visit_id
        self.track_id = None
        self.camera = None
        self.ts = None
        self.total_dwell_ms = 0
        self.zones_count = 0
        self.cash_passes = 0
        self.dark_top = 0.0
        self.dark_bot = 0.0


def aggregate_visits(events: List) -> Dict[str, VisitAgg]:
    """Collapse the event stream into one record per visit_id."""
    visits: Dict[str, VisitAgg] = {}

    def get(vid) -> VisitAgg:
        if vid not in visits:
            visits[vid] = VisitAgg(vid)
        return visits[vid]

    for e in events:
        p = e.payload
        vid = getattr(p, "visit_id", None)
        if vid is None:
            continue
        v = get(vid)
        if e.camera and v.camera is None:
            v.camera = e.camera
        if v.track_id is None and getattr(p, "track_id", None) is not None:
            v.track_id = p.track_id
        if e.type == "visit.ended":
            v.total_dwell_ms = p.total_dwell_ms
            v.zones_count = len(p.zones_visited)
            v.ts = e.ts
            v.dark_top = getattr(p, "outfit_dark_top", 0.0)
            v.dark_bot = getattr(p, "outfit_dark_bot", 0.0)
        elif e.type == "visit.approached_cash":
            v.cash_passes += 1
    return visits


def per_camera_median_dwell(visits: Dict[str, VisitAgg]) -> Dict[Optional[str], float]:
    by_cam: Dict[Optional[str], List[int]] = defaultdict(list)
    for v in visits.values():
        if v.total_dwell_ms > 0:
            by_cam[v.camera].append(v.total_dwell_ms)
    return {cam: statistics.median(d) for cam, d in by_cam.items() if d}


def classify(
    visits: Dict[str, VisitAgg],
    *,
    dwell_floor_s: float,
    dwell_median_mult: float,
    zones_min: int,
    min_signals: int,
    dark_threshold: float = DEFAULT_DARK_THRESHOLD,
    uniform_rule: str = DEFAULT_UNIFORM_RULE,
    uniform_min_dwell_s: float = DEFAULT_UNIFORM_MIN_DWELL_S,
) -> List[str]:
    """
    Return the list of visit_ids classified as staff.

    Staff = uniform match OR (>= min_signals behavioral signals). The detection
    field names still say "dark" for compatibility, but they carry the
    configured store-uniform match fraction (black for Store 1, pink for Store 2).
    """
    medians = per_camera_median_dwell(visits)
    floor_ms = dwell_floor_s * 1000
    staff: List[str] = []

    for vid, v in visits.items():
        if v.ts is None:
            continue  # no visit.ended -> skip (can't score)

        med = medians.get(v.camera, 0)
        long_dwell = v.total_dwell_ms > floor_ms or (
            med > 0 and v.total_dwell_ms > dwell_median_mult * med
        )
        multi_zone = v.zones_count >= zones_min
        cash_anchor = v.cash_passes >= 1 and long_dwell

        dwell_ok = v.total_dwell_ms >= uniform_min_dwell_s * 1000
        if uniform_rule == "top_only":
            uniform_match = v.dark_top >= dark_threshold
        else:
            uniform_match = v.dark_top >= dark_threshold and v.dark_bot >= dark_threshold
        uniform_match = uniform_match and dwell_ok
        behavioral = sum([long_dwell, multi_zone, cash_anchor]) >= min_signals

        if uniform_match or behavioral:
            staff.append(vid)
    return staff


def build_staff_events(visits: Dict[str, VisitAgg], staff_ids: List[str]) -> List:
    from ulid import ULID
    out = []
    for vid in staff_ids:
        v = visits[vid]
        out.append(
            TrackStaffClassified(
                event_id=str(ULID()),
                ts=v.ts,
                camera=v.camera,
                payload=TrackStaffClassifiedPayload(
                    visit_id=vid,
                    track_id=v.track_id if v.track_id is not None else 0,
                    evidence=StaffEvidence(
                        total_dwell_ms=v.total_dwell_ms,
                        zones_count=v.zones_count,
                        cash_passes=v.cash_passes,
                        outfit_dark_top=v.dark_top,
                        outfit_dark_bot=v.dark_bot,
                    ),
                ),
            )
        )
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Behavioral staff classification pass")
    p.add_argument("--in", dest="in_path", default="events/events.jsonl")
    p.add_argument("--out", dest="out_path", default="events/events.classified.jsonl")
    p.add_argument("--store", help="Store id selecting classifier uniform thresholds")
    p.add_argument("--dwell-floor-s", type=float, default=DEFAULT_DWELL_FLOOR_S,
                   help="Absolute long-dwell floor in seconds (full-day: 1800)")
    p.add_argument("--dwell-median-mult", type=float, default=DEFAULT_DWELL_MEDIAN_MULT,
                   help="OR dwell > this * per-camera median dwell")
    p.add_argument("--zones-min", type=int, default=DEFAULT_ZONES_MIN,
                   help="Multi-zone signal threshold (full-day: 3)")
    p.add_argument("--min-signals", type=int, default=DEFAULT_MIN_SIGNALS,
                   help="Behavioral signals required to classify as staff")
    p.add_argument("--dark-threshold", type=float, default=None,
                   help="Median top&bottom clothing darkness >= this => black outfit")
    p.add_argument("--uniform-rule", choices=("top_and_bottom", "top_only"), default=None,
                   help="Uniform match rule for the per-detection top/bottom fractions")
    p.add_argument("--uniform-min-dwell-s", type=float, default=None,
                   help="Minimum visit dwell before a uniform match can classify staff")
    return p.parse_args()


def main():
    args = parse_args()
    configure_logging()
    log = logger.bind(in_path=args.in_path, out_path=args.out_path)

    events = load_jsonl(args.in_path)
    visits = aggregate_visits(events)
    cfg = classifier_config(args.store) if args.store and classifier_config else {}
    staff_ids = classify(
        visits,
        dwell_floor_s=args.dwell_floor_s,
        dwell_median_mult=args.dwell_median_mult,
        zones_min=args.zones_min,
        min_signals=args.min_signals,
        dark_threshold=(
            args.dark_threshold if args.dark_threshold is not None
            else cfg.get("uniform_threshold", DEFAULT_DARK_THRESHOLD)
        ),
        uniform_rule=args.uniform_rule or cfg.get("uniform_rule", DEFAULT_UNIFORM_RULE),
        uniform_min_dwell_s=(
            args.uniform_min_dwell_s if args.uniform_min_dwell_s is not None
            else cfg.get("uniform_min_dwell_s", DEFAULT_UNIFORM_MIN_DWELL_S)
        ),
    )
    staff_events = build_staff_events(visits, staff_ids)

    # Output = original events + the new staff classifications, time-ordered.
    combined = list(events) + staff_events
    combined.sort(key=lambda e: e.ts)
    written = dump_jsonl(combined, args.out_path)

    # Summary stats.
    staff_set = set(staff_ids)
    customer_dwell_s = sorted(
        v.total_dwell_ms / 1000 for vid, v in visits.items()
        if vid not in staff_set and v.ts
    )
    median_customer_dwell = (
        round(statistics.median(customer_dwell_s), 1) if customer_dwell_s else 0.0
    )
    log.info(
        "classification_complete",
        total_visits=len(visits),
        staff_classified=len(staff_ids),
        customer_visits_remaining=len(visits) - len(staff_ids),
        median_customer_dwell_s=median_customer_dwell,
        events_in=len(events),
        events_out=written,
    )


if __name__ == "__main__":
    main()
