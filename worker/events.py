"""
Business-event derivation: raw_detections.jsonl -> events.jsonl.

Consumes per-frame, per-track detections (from detect.py) and produces the
typed business events defined in worker/schemas.py using line crossing, zone
polygon containment, group detection, and temporal+spatial re-entry gating.

Pure, unit-testable helpers (imported by tests):
  cross_line(p_prev, p_curr, line)   -> bool
  point_in_zone(p, polygon_points)   -> bool
  gate_reentry(candidates, pos, ts)  -> Optional[str]   (visit_id)

Run from the worker/ directory:
  python events.py --in events/raw_detections.jsonl --out events/events.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import structlog
from shapely.geometry import Point, Polygon
from ulid import ULID

from schemas import (
    VisitApproachedCash,
    VisitApproachedCashPayload,
    VisitEnded,
    VisitEndedPayload,
    VisitEntered,
    VisitEnteredPayload,
    VisitEnteredZone,
    VisitEnteredZonePayload,
    VisitExitedZone,
    VisitExitedZonePayload,
    dump_jsonl,
)

logger = structlog.get_logger()

Pt = Tuple[float, float]

# Tunables (overridable via CLI)
END_TIMEOUT_S = 10.0
REENTRY_GATE_S = 8.0
REENTRY_GATE_PX = 100.0
GROUP_WINDOW_S = 3.0
GROUP_GATE_PX = 150.0


# ---------------------------------------------------------------------------
# Geometry (pure functions)
# ---------------------------------------------------------------------------


def feet_point(bbox: Sequence[float]) -> Pt:
    """Bottom-center of a bbox [x1,y1,x2,y2] — the person's floor position."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)


def _orient(a: Pt, b: Pt, c: Pt) -> float:
    """Cross product sign of (b-a) x (c-a)."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(p1: Pt, p2: Pt, p3: Pt, p4: Pt) -> bool:
    """True if segment p1p2 properly crosses segment p3p4."""
    d1 = _orient(p3, p4, p1)
    d2 = _orient(p3, p4, p2)
    d3 = _orient(p1, p2, p3)
    d4 = _orient(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def cross_line(p_prev: Pt, p_curr: Pt, line: dict) -> bool:
    """
    True when the path p_prev -> p_curr crosses the oriented line in the
    configured "in" direction. ``line`` = {"points": [[x,y],[x,y]], "direction": ...}.

    Supported directions:
      in_when_y_decreases / in_when_y_increases
      in_when_x_decreases / in_when_x_increases
    A touch at a shared endpoint (parallel / no proper crossing) returns False.
    """
    a, b = line["points"][0], line["points"][1]
    if not _segments_intersect(p_prev, p_curr, tuple(a), tuple(b)):
        return False
    direction = line.get("direction", "in_when_y_decreases")
    dx = p_curr[0] - p_prev[0]
    dy = p_curr[1] - p_prev[1]
    if direction == "in_when_y_decreases":
        return dy < 0
    if direction == "in_when_y_increases":
        return dy > 0
    if direction == "in_when_x_decreases":
        return dx < 0
    if direction == "in_when_x_increases":
        return dx > 0
    return True


def _within(pt: Point, poly: Polygon) -> bool:
    # Boundary-inclusive: a person standing exactly on the edge still counts.
    return pt.within(poly) or pt.touches(poly)


def point_in_zone(p: Pt, polygon_points: Sequence[Sequence[float]]) -> bool:
    """True if point p is inside (or on the boundary of) the polygon."""
    return _within(Point(p), Polygon([tuple(pt) for pt in polygon_points]))


def _dist(a: Pt, b: Pt) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ---------------------------------------------------------------------------
# Track state
# ---------------------------------------------------------------------------


@dataclass
class TrackState:
    track_id: int
    visit_id: str
    first_seen_ts: datetime
    last_seen_ts: datetime
    last_position: Pt
    entered: bool = False
    entry_ts: Optional[datetime] = None
    group_id: Optional[str] = None
    approached_cash: bool = False
    inside_zones: Set[str] = field(default_factory=set)
    zone_enter_ts: Dict[str, datetime] = field(default_factory=dict)
    zones_visited: Set[str] = field(default_factory=set)
    ended: bool = False
    merged: bool = False  # adopted by a re-entry continuation
    # Per-detection clothing-darkness samples (staff wear all-black).
    top_dark_samples: List[float] = field(default_factory=list)
    bot_dark_samples: List[float] = field(default_factory=list)


def gate_reentry(
    candidates: Sequence[TrackState],
    new_pos: Pt,
    new_ts: datetime,
    gate_seconds: float = REENTRY_GATE_S,
    gate_px: float = REENTRY_GATE_PX,
) -> Optional[str]:
    """
    Return the visit_id of the nearest still-open track that went quiet within
    ``gate_seconds`` and within ``gate_px`` of ``new_pos`` — i.e. the same
    person re-detected under a fresh track id. None if no match.
    """
    st = _match_reentry(candidates, new_pos, new_ts, gate_seconds, gate_px)
    return st.visit_id if st is not None else None


def _match_reentry(
    candidates: Sequence[TrackState],
    new_pos: Pt,
    new_ts: datetime,
    gate_seconds: float,
    gate_px: float,
) -> Optional[TrackState]:
    best: Optional[TrackState] = None
    best_d = float("inf")
    for s in candidates:
        if s.ended or s.merged:
            continue
        gap = (new_ts - s.last_seen_ts).total_seconds()
        if gap < 0 or gap > gate_seconds:
            continue
        d = _dist(new_pos, s.last_position)
        if d <= gate_px and d < best_d:
            best, best_d = s, d
    return best


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


def _ms(delta: timedelta) -> int:
    return int(delta.total_seconds() * 1000)


class EventDeriver:
    def __init__(self, zones: dict, *, camera: Optional[str] = None,
                 end_timeout_s=END_TIMEOUT_S,
                 reentry_s=REENTRY_GATE_S, reentry_px=REENTRY_GATE_PX):
        self.camera = camera
        self.end_timeout_s = end_timeout_s
        self.reentry_s = reentry_s
        self.reentry_px = reentry_px

        # entry_line is OPTIONAL: a camera that doesn't see the doorway (interior
        # or cash-counter feed) has no line. On such cameras a track is "active"
        # from its first detection so zone/cash events still fire, but no
        # visit.entered is emitted (footfall is owned by the door camera).
        self.entry_line = zones.get("entry_line")
        # Polygon zones excluding the entry line and the cash counter
        self.polygon_zones: Dict[str, Polygon] = {}
        for name, z in zones.items():
            if name.startswith("_") or name == "entry_line":
                continue
            if z.get("type") == "polygon" and name != "cash_counter":
                self.polygon_zones[name] = Polygon([tuple(p) for p in z["points"]])
        self.cash_poly: Optional[Polygon] = (
            Polygon([tuple(p) for p in zones["cash_counter"]["points"]])
            if "cash_counter" in zones
            else None
        )

        self.tracks: Dict[int, TrackState] = {}
        self.events: list = []
        # recent entries for group detection: (ts, pos, group_id)
        self._recent_entries: List[Tuple[datetime, Pt, str]] = []
        self._last_scan_frame: Optional[int] = None

    # -- helpers ----------------------------------------------------------

    def _new_id(self) -> str:
        return str(ULID())

    def _assign_group(self, ts: datetime, pos: Pt) -> Tuple[str, int]:
        self._recent_entries = [
            (t, p, g) for (t, p, g) in self._recent_entries
            if (ts - t).total_seconds() <= GROUP_WINDOW_S
        ]
        gid: Optional[str] = None
        for (_, p, g) in self._recent_entries:
            if _dist(pos, p) <= GROUP_GATE_PX:
                gid = g
                break
        if gid is None:
            gid = self._new_id()
        self._recent_entries.append((ts, pos, gid))
        size = sum(1 for (_, _, g) in self._recent_entries if g == gid)
        return gid, size

    # -- event emitters ---------------------------------------------------

    def _emit_entered(self, st: TrackState, ts: datetime):
        gid, size = self._assign_group(ts, st.last_position)
        st.group_id = gid
        self.events.append(VisitEntered(
            event_id=self._new_id(), ts=ts, camera=self.camera,
            payload=VisitEnteredPayload(
                visit_id=st.visit_id, track_id=st.track_id,
                entry_line="entry_line", group_id=gid, group_size=size),
        ))

    def _emit_entered_zone(self, st: TrackState, zone: str, ts: datetime):
        self.events.append(VisitEnteredZone(
            event_id=self._new_id(), ts=ts, camera=self.camera,
            payload=VisitEnteredZonePayload(
                visit_id=st.visit_id, track_id=st.track_id, zone=zone),
        ))

    def _emit_exited_zone(self, st: TrackState, zone: str, ts: datetime, dwell_ms: int):
        self.events.append(VisitExitedZone(
            event_id=self._new_id(), ts=ts, camera=self.camera,
            payload=VisitExitedZonePayload(
                visit_id=st.visit_id, track_id=st.track_id,
                zone=zone, dwell_ms=dwell_ms),
        ))

    def _emit_approached_cash(self, st: TrackState, ts: datetime):
        self.events.append(VisitApproachedCash(
            event_id=self._new_id(), ts=ts, camera=self.camera,
            payload=VisitApproachedCashPayload(
                visit_id=st.visit_id, track_id=st.track_id),
        ))

    def _emit_ended(self, st: TrackState, ts: datetime, reason: str):
        # Close any still-open zones so dwell stats are complete.
        for zone in sorted(list(st.inside_zones)):
            dwell = _ms(ts - st.zone_enter_ts.get(zone, ts))
            self._emit_exited_zone(st, zone, ts, dwell)
        st.inside_zones.clear()
        start = st.entry_ts or st.first_seen_ts

        def _median(xs: List[float]) -> float:
            if not xs:
                return 0.0
            s = sorted(xs)
            n = len(s)
            mid = n // 2
            return round(s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2, 3)

        self.events.append(VisitEnded(
            event_id=self._new_id(), ts=ts, camera=self.camera,
            payload=VisitEndedPayload(
                visit_id=st.visit_id, track_id=st.track_id,
                total_dwell_ms=_ms(ts - start),
                zones_visited=sorted(st.zones_visited), reason=reason,
                outfit_dark_top=_median(st.top_dark_samples),
                outfit_dark_bot=_median(st.bot_dark_samples)),
        ))
        st.ended = True

    # -- core -------------------------------------------------------------

    def _scan_for_ended(self, now: datetime):
        for st in list(self.tracks.values()):
            if st.ended or st.merged or not st.entered:
                continue
            if (now - st.last_seen_ts).total_seconds() > self.end_timeout_s:
                self._emit_ended(st, st.last_seen_ts, "track_lost")

    def process_detection(self, frame: int, ts: datetime, track_id: int,
                          bbox: Sequence[float], top_dark: float = 0.0,
                          bot_dark: float = 0.0):
        pos = feet_point(bbox)

        # Frame advanced -> sweep for tracks that have gone quiet.
        if self._last_scan_frame is not None and frame != self._last_scan_frame:
            self._scan_for_ended(ts)
        self._last_scan_frame = frame

        st = self.tracks.get(track_id)
        if st is None:
            reused = _match_reentry(
                list(self.tracks.values()), pos, ts, self.reentry_s, self.reentry_px)
            if reused is not None:
                # Continuation of the same person under a new track id.
                reused.merged = True
                st = TrackState(
                    track_id=track_id, visit_id=reused.visit_id,
                    first_seen_ts=reused.first_seen_ts, last_seen_ts=ts,
                    last_position=pos, entered=reused.entered,
                    entry_ts=reused.entry_ts, group_id=reused.group_id,
                    approached_cash=reused.approached_cash,
                    inside_zones=set(reused.inside_zones),
                    zone_enter_ts=dict(reused.zone_enter_ts),
                    zones_visited=set(reused.zones_visited),
                    top_dark_samples=list(reused.top_dark_samples),
                    bot_dark_samples=list(reused.bot_dark_samples),
                )
            else:
                st = TrackState(
                    track_id=track_id, visit_id=self._new_id(),
                    first_seen_ts=ts, last_seen_ts=ts, last_position=pos)
                # No doorway on this camera -> the track is active immediately
                # (so zone/cash events fire) but we don't claim a footfall entry.
                if self.entry_line is None:
                    st.entered = True
                    st.entry_ts = ts
            self.tracks[track_id] = st

        # Record clothing-darkness samples for this detection (skip empty crops).
        if top_dark or bot_dark:
            st.top_dark_samples.append(top_dark)
            st.bot_dark_samples.append(bot_dark)

        prev_pos = st.last_position

        # Entry line crossing (door cameras only)
        if self.entry_line is not None and not st.entered \
                and cross_line(prev_pos, pos, self.entry_line):
            st.entered = True
            st.entry_ts = ts
            self._emit_entered(st, ts)

        # Polygon zone enter/exit
        for zname, poly in self.polygon_zones.items():
            inside = _within(Point(pos), poly)
            if inside and zname not in st.inside_zones:
                st.inside_zones.add(zname)
                st.zone_enter_ts[zname] = ts
                st.zones_visited.add(zname)
                self._emit_entered_zone(st, zname, ts)
            elif not inside and zname in st.inside_zones:
                dwell = _ms(ts - st.zone_enter_ts.get(zname, ts))
                st.inside_zones.discard(zname)
                self._emit_exited_zone(st, zname, ts, dwell)

        # Cash counter (once per visit)
        if self.cash_poly is not None and not st.approached_cash:
            if _within(Point(pos), self.cash_poly):
                st.approached_cash = True
                st.zones_visited.add("cash_counter")
                self._emit_approached_cash(st, ts)

        st.last_position = pos
        st.last_seen_ts = ts

    def finalize(self):
        """Close all open visits at end of footage."""
        for st in self.tracks.values():
            if st.ended or st.merged or not st.entered:
                continue
            self._emit_ended(st, st.last_seen_ts, "end_of_footage")
        # Time-order the output.
        self.events.sort(key=lambda e: e.ts)
        return self.events


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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


def _read_detections(path: Path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Derive business events from raw detections")
    p.add_argument("--in", dest="in_path", default="events/raw_detections.jsonl")
    p.add_argument("--out", dest="out_path", default="events/events.jsonl")
    p.add_argument("--zones", default="zones.json")
    p.add_argument("--camera", default=None,
                   help="Camera label stamped onto every emitted event (e.g. cam3)")
    p.add_argument("--end-timeout-s", type=float, default=END_TIMEOUT_S)
    p.add_argument("--reentry-gate-s", type=float, default=REENTRY_GATE_S)
    p.add_argument("--reentry-gate-px", type=float, default=REENTRY_GATE_PX)
    return p.parse_args()


def main():
    args = parse_args()
    configure_logging()
    log = logger.bind(in_path=args.in_path, out_path=args.out_path)

    zones_all = json.loads(Path(args.zones).read_text())
    # Camera-keyed config: select this camera's sub-dict (e.g. zones["cam3"]).
    # Fall back to the flat top-level dict for single-camera / legacy configs.
    if args.camera and isinstance(zones_all.get(args.camera), dict):
        zones = zones_all[args.camera]
    else:
        zones = zones_all
    deriver = EventDeriver(
        zones, camera=args.camera, end_timeout_s=args.end_timeout_s,
        reentry_s=args.reentry_gate_s, reentry_px=args.reentry_gate_px)

    n_det = 0
    # Sort by frame then track_id so per-frame sweeps are deterministic.
    rows = sorted(_read_detections(Path(args.in_path)),
                  key=lambda r: (r["frame"], r["track_id"]))
    for r in rows:
        ts = datetime.fromisoformat(r["ts"])
        deriver.process_detection(
            r["frame"], ts, r["track_id"], r["bbox"],
            top_dark=r.get("top_dark", 0.0), bot_dark=r.get("bot_dark", 0.0))
        n_det += 1

    events = deriver.finalize()
    written = dump_jsonl(events, args.out_path)

    counts: Dict[str, int] = {}
    for e in events:
        counts[e.type] = counts.get(e.type, 0) + 1
    log.info("derivation_complete", camera=args.camera, detections_in=n_det,
             events_out=written,
             unique_visits=len({getattr(e.payload, "visit_id", None) for e in events}),
             by_type=counts)


if __name__ == "__main__":
    main()
