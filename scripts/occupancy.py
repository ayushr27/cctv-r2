#!/usr/bin/env python3
"""
Occupancy summary — peak-concurrent + de-fragmented visitor counts per camera.

WHY THIS EXISTS
---------------
BoT-SORT fragments one shopper into several track-ids on these CCTV clips (a brief
occlusion ends a track; the person reappears under a new id), so "distinct
track-ids" badly over-counts footfall. The raw per-frame data showed ~6-8 people
on-camera at once but 26-49 distinct ids per camera. This script derives two
fragmentation-aware numbers per camera straight from the raw detections:

  peak     max distinct track-ids visible in ANY single frame — how many people
           were on-camera at once. Immune to fragmentation: a fragment is a new id
           only when the person is NOT in the same frame, so it never lifts peak.
  visitors distinct track-ids AFTER merging fragments — ids whose lifespans are
           disjoint in time and whose hand-off positions are close collapse into
           one person (the same idea as the events.py re-entry gate, applied to
           raw track-ids). An estimate of "how many distinct people passed through".
  distinct raw distinct track-ids (kept so the UI can show the inflation delta).

Output: events/<STORE_ID>/occupancy.json = {camera: {peak, distinct, visitors}}.

Pure stdlib (no cv2/torch/ultralytics) so it runs in OR out of the worker image —
the API never reads raw footage, it reads this small JSON summary.

Usage:
  occupancy.py events/STORE_BLR_002                       # every raw_*.jsonl in dir
  occupancy.py events/STORE_BLR_002 --out path/occupancy.json
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

# Fragment-merge gate: a track that starts within MERGE_GAP_MS after another
# track ended, and within MERGE_DIST_PX of where it ended, is treated as the same
# person reappearing. Conservative (short gap, modest distance) so two genuinely
# different shoppers are not merged. Heuristic — documented in CHOICES.md.
MERGE_GAP_MS = 5000
MERGE_DIST_PX = 250.0


def _feet(bbox: List[float]) -> Tuple[float, float]:
    """Bottom-center of [x1,y1,x2,y2] — the person's floor position."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def camera_occupancy(rows: List[dict]) -> Dict[str, int]:
    """{peak, distinct, visitors} for one camera's raw detections."""
    if not rows:
        return {"peak": 0, "distinct": 0, "visitors": 0}

    # Peak concurrent: max distinct track-ids sharing a frame.
    by_frame: Dict[int, set] = defaultdict(set)
    for r in rows:
        by_frame[r["frame"]].add(r["track_id"])
    peak = max((len(s) for s in by_frame.values()), default=0)

    # Per-track span + hand-off positions (use video_ts_ms when present, else frame).
    first_ms: Dict[int, int] = {}
    last_ms: Dict[int, int] = {}
    first_pos: Dict[int, Tuple[float, float]] = {}
    last_pos: Dict[int, Tuple[float, float]] = {}
    for r in sorted(rows, key=lambda r: (r.get("video_ts_ms", r["frame"]), r["track_id"])):
        t = r["track_id"]
        ms = int(r.get("video_ts_ms", r["frame"] * 200))  # ~5fps fallback
        pos = _feet(r["bbox"])
        if t not in first_ms:
            first_ms[t] = ms
            first_pos[t] = pos
        last_ms[t] = ms
        last_pos[t] = pos

    distinct = len(first_ms)

    # Union-find merge of fragments: attach each track to the nearest earlier track
    # that ended just before it began, close to its first position.
    parent: Dict[int, int] = {t: t for t in first_ms}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    order = sorted(first_ms, key=lambda t: first_ms[t])
    for i, t in enumerate(order):
        best, best_d = None, float("inf")
        for p in order[:i]:
            if find(p) == find(t):
                continue
            gap = first_ms[t] - last_ms[p]
            if gap < 0 or gap > MERGE_GAP_MS:
                continue
            d = _dist(last_pos[p], first_pos[t])
            if d <= MERGE_DIST_PX and d < best_d:
                best, best_d = p, d
        if best is not None:
            parent[find(t)] = find(best)

    visitors = len({find(t) for t in first_ms})
    return {"peak": peak, "distinct": distinct, "visitors": visitors}


def summarize(store_dir: str) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for path in sorted(glob.glob(os.path.join(store_dir, "raw_*.jsonl"))):
        cam = os.path.basename(path)[len("raw_"):-len(".jsonl")]
        rows = [json.loads(l) for l in open(path) if l.strip()]
        out[cam] = camera_occupancy(rows)
    return out


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("store_dir", help="events/<STORE_ID> directory holding raw_*.jsonl")
    ap.add_argument("--out", help="output path (default: <store_dir>/occupancy.json)")
    args = ap.parse_args(argv)

    summary = summarize(args.store_dir)
    dst = args.out or os.path.join(args.store_dir, "occupancy.json")
    with open(dst, "w") as f:
        json.dump(summary, f, indent=2)
    peak = max((c["peak"] for c in summary.values()), default=0)
    print(f"occupancy -> {dst}  cameras={list(summary)}  busiest_peak={peak}")
    for cam, c in summary.items():
        print(f"  {cam}: peak={c['peak']} distinct={c['distinct']} visitors={c['visitors']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
