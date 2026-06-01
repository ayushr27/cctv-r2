"""
Anomaly detection — a small registry of pluggable detectors.

Each detector implements the ``Detector`` protocol and is registered in
``DETECTORS``. The /anomaly route iterates the registry, so a new detector is
added by writing a class and appending it to the list — the route never
changes (plan acceptance: "new detectors can be added without touching the
route").

Every detector returns a list of anomaly dicts shaped like
``AnomalyDetectedPayload`` (kind, severity, window{from,to}, observed,
expected_p50, z_score, evidence) so the route can serialize them directly.

Note on this dataset: the CV footage is a ~3-minute sample while the POS spans
a full day, so the footfall/conversion baselines are thin on REAL data
(FootfallDrop/ConversionDrop need volume to be meaningful). ZoneStarvation
fires readily on real data (every zone is empty for most of the day). The unit
tests drive each detector with synthetic event streams to prove all three fire
and correctly stay silent — which is the acceptance path the plan allows.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Protocol

IST = timezone(timedelta(hours=5, minutes=30))
BUCKET_MS = 5 * 60 * 1000


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ms(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return int(dt.timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=IST).isoformat()


def _hour_iso(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=IST).replace(minute=0, second=0, microsecond=0)
    return dt.isoformat()


class Window:
    """A resolved [from, to] query window (ISO strings + epoch ms)."""

    def __init__(self, from_: Optional[str], to: Optional[str]):
        self.from_ = from_
        self.to = to
        self.from_ms = _ms(from_)
        self.to_ms = _ms(to)


class Detector(Protocol):
    kind: str

    def run(self, store, pos, window: Window) -> List[dict]:
        ...


# ---------------------------------------------------------------------------
# 1) Footfall drop
# ---------------------------------------------------------------------------


class FootfallDropDetector:
    kind = "footfall_drop"
    ROLL = 12  # 12 * 5-min = 60-min rolling baseline

    def run(self, store, pos, window: Window) -> List[dict]:
        staff = getattr(store, "staff_visit_ids", set())
        events = store.get_events(window.from_, window.to, type_="visit.entered", limit=100000)
        stamps = sorted(
            _ms(e["ts"]) for e in events if e["payload"].get("visit_id") not in staff
        )
        if not stamps:
            return []

        buckets: Dict[int, int] = {}
        for s in stamps:
            buckets[s // BUCKET_MS] = buckets.get(s // BUCKET_MS, 0) + 1

        lo, hi = min(buckets), max(buckets)
        out: List[dict] = []
        for b in range(lo, hi + 1):
            observed = buckets.get(b, 0)
            baseline = [buckets.get(x, 0) for x in range(b - self.ROLL, b)]
            if len(baseline) < 3:
                continue
            p50 = statistics.median(baseline)
            stdev = statistics.pstdev(baseline) if len(baseline) > 1 else 0.0
            if p50 <= 0 or stdev <= 0:
                continue
            z = (observed - p50) / stdev
            if observed < p50 - 2 * stdev and observed < 0.5 * p50:
                severity = "critical" if z < -3 else "warning"
                start = b * BUCKET_MS
                out.append(
                    {
                        "kind": self.kind,
                        "severity": severity,
                        "window": {"from": _iso(start), "to": _iso(start + BUCKET_MS)},
                        "observed": float(observed),
                        "expected_p50": float(p50),
                        "z_score": round(z, 2),
                        "evidence": (
                            f"Footfall in this 5-min bucket is {observed} vs rolling "
                            f"60-min median {p50:.0f} ({z:.1f}σ below baseline)."
                        ),
                    }
                )
        return out


# ---------------------------------------------------------------------------
# 2) Conversion drop
# ---------------------------------------------------------------------------


class ConversionDropDetector:
    kind = "conversion_drop"
    MIN_FOOTFALL = 10

    def run(self, store, pos, window: Window) -> List[dict]:
        staff = getattr(store, "staff_visit_ids", set())
        events = store.get_events(window.from_, window.to, type_="visit.entered", limit=100000)

        foot_by_hour: Dict[str, int] = {}
        for e in events:
            if e["payload"].get("visit_id") in staff:
                continue
            h = _hour_iso(_ms(e["ts"]))
            foot_by_hour[h] = foot_by_hour.get(h, 0) + 1

        bill_by_hour: Dict[str, int] = {}
        for b in pos.get_bills(window.from_, window.to):
            h = _hour_iso(b.ts_ms)
            bill_by_hour[h] = bill_by_hour.get(h, 0) + 1

        hourly_conv = {
            h: bill_by_hour.get(h, 0) / foot for h, foot in foot_by_hour.items() if foot > 0
        }
        if not hourly_conv:
            return []
        daily_median = statistics.median(hourly_conv.values())
        if daily_median <= 0:
            return []

        out: List[dict] = []
        for hour, conv in sorted(hourly_conv.items()):
            foot = foot_by_hour[hour]
            if foot > self.MIN_FOOTFALL and conv < 0.5 * daily_median:
                h_ms = _ms(hour)
                out.append(
                    {
                        "kind": self.kind,
                        "severity": "warning",
                        "window": {"from": hour, "to": _iso(h_ms + 3600 * 1000)},
                        "observed": round(conv, 4),
                        "expected_p50": round(daily_median, 4),
                        "z_score": None,
                        "evidence": (
                            f"Hourly conversion {conv:.1%} ({bill_by_hour.get(hour, 0)} bills / "
                            f"{foot} footfall) is below half the daily median {daily_median:.1%}."
                        ),
                    }
                )
        return out


# ---------------------------------------------------------------------------
# 3) Zone starvation
# ---------------------------------------------------------------------------


class ZoneStarvationDetector:
    kind = "zone_starvation"
    OPEN_HOUR = 10
    CLOSE_HOUR = 22
    GAP_MIN = 45

    def run(self, store, pos, window: Window) -> List[dict]:
        events = store.get_events(window.from_, window.to, type_="visit.entered_zone", limit=100000)
        by_zone: Dict[str, List[int]] = {}
        for e in events:
            zone = e["payload"].get("zone")
            if zone:
                by_zone.setdefault(zone, []).append(_ms(e["ts"]))
        if not by_zone:
            return []

        # anchor open/close to the day implied by the first observed event
        first_ms = min(min(v) for v in by_zone.values())
        day = datetime.fromtimestamp(first_ms / 1000, tz=IST)
        open_ms = int(day.replace(hour=self.OPEN_HOUR, minute=0, second=0, microsecond=0).timestamp() * 1000)
        close_ms = int(day.replace(hour=self.CLOSE_HOUR, minute=0, second=0, microsecond=0).timestamp() * 1000)
        gap_ms = self.GAP_MIN * 60 * 1000

        out: List[dict] = []
        for zone, stamps in sorted(by_zone.items()):
            stamps = sorted(s for s in stamps if s is not None and open_ms <= s <= close_ms)
            points = [open_ms] + stamps + [close_ms]
            for i in range(len(points) - 1):
                start, end = points[i], points[i + 1]
                gap = end - start
                if gap >= gap_ms:
                    minutes = gap / 60000
                    severity = "info" if minutes < 60 else "warning"
                    out.append(
                        {
                            "kind": self.kind,
                            "severity": severity,
                            "window": {"from": _iso(start), "to": _iso(end)},
                            "observed": 0.0,
                            "expected_p50": None,
                            "z_score": None,
                            "evidence": (
                                f"Zone '{zone}' had no visit.entered_zone for "
                                f"{minutes:.0f} min during open hours."
                            ),
                        }
                    )
        return out


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

DETECTORS: List[Detector] = [
    FootfallDropDetector(),
    ConversionDropDetector(),
    ZoneStarvationDetector(),
]

_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def run_detectors(
    store,
    pos,
    from_: Optional[str],
    to: Optional[str],
    kinds: Optional[List[str]] = None,
) -> List[dict]:
    """Run all (or a filtered subset of) detectors and return sorted anomalies."""
    window = Window(from_, to)
    results: List[dict] = []
    for det in DETECTORS:
        if kinds and det.kind not in kinds:
            continue
        results.extend(det.run(store, pos, window))
    results.sort(key=lambda a: (_SEVERITY_RANK.get(a["severity"], 9), a["window"]["from"]))
    return results
