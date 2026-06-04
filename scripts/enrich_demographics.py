#!/usr/bin/env python3
"""
Best-effort demographic enrichment for canonical ENTRY events.

WHAT THIS IS (and is not)
-------------------------
The challenge footage is FACE-BLURRED, so face-based age/gender models cannot
run. ``worker/demographics.py`` ships the *real* path: a VLM (Anthropic Haiku)
prompted on the person crop's body/clothing cues, enabled with
``DEMOGRAPHICS_BACKEND=vlm`` + ``ANTHROPIC_API_KEY``. That path needs the raw
crops and an API key, which a CPU-only / offline demo box does not have.

This script is the **offline stand-in** for that backend: it attaches a
deterministic, clearly-directional demographic distribution to the first event of
each distinct visitor (so the panel covers every in-store shopper, not only the
few who crossed a doorway) so the dashboard's Demographics panel is populated for
the demo. It is:
  * deterministic (hash of visitor_id) -> reproducible, not random per run;
  * idempotent (skips events that already carry ``gender_pred``);
  * flagged ``is_face_hidden=true`` on every event, like the real backend;
  * aggregate-only -- no identity is stored, the numbers are low-confidence.

It is NOT a real inference. In production you would delete this and let the VLM
backend write the same metadata fields. Documented in CHOICES.md.

Usage:
  enrich_demographics.py events/canonical.seed.jsonl              # in place
  enrich_demographics.py in.jsonl --out out.jsonl                 # to a new file
  enrich_demographics.py in.jsonl --store-id STORE_BLR_009        # one store only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

# Directional distribution for a beauty/cosmetics store (skews female, 18-34).
# (gender, age_bucket, representative_age, cumulative_weight 0-999)
_DISTRIBUTION = [
    ("F", "18-24", 21, 230),
    ("F", "25-34", 29, 520),
    ("F", "35-44", 39, 650),
    ("F", "45-54", 49, 700),
    ("M", "18-24", 22, 800),
    ("M", "25-34", 30, 920),
    ("M", "35-44", 40, 980),
    ("M", "45-54", 50, 1000),
]


def _estimate(visitor_id: str) -> dict:
    """Deterministic best-effort demographic guess from the visitor id hash."""
    h = int(hashlib.sha1(visitor_id.encode()).hexdigest(), 16) % 1000
    for gender, bucket, age, ceiling in _DISTRIBUTION:
        if h < ceiling:
            return {
                "gender_pred": gender,
                "age_pred": age,
                "age_bucket": bucket,
                "is_face_hidden": True,
            }
    return {"gender_pred": "F", "age_pred": 29, "age_bucket": "25-34", "is_face_hidden": True}


def enrich(src: str, dst: str, store_id: str | None = None) -> tuple[int, int]:
    rows = []
    tagged = total = 0
    seen: set = set()
    with open(src) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            rows.append(ev)
            if store_id is not None and ev.get("store_id") != store_id:
                continue
            # Tag the FIRST event of each distinct visitor (canonical is time-
            # sorted), NOT only ENTRY: floor-only shoppers never cross the doorway,
            # so an ENTRY-only tag described just the handful of door-crossers and
            # left the panel covering ~2 of ~30 visitors. One estimate per visitor.
            key = (ev.get("store_id"), ev.get("visitor_id"))
            if key in seen:
                continue
            seen.add(key)
            total += 1
            meta = ev.setdefault("metadata", {})
            if not meta.get("gender_pred"):  # idempotent
                meta.update(_estimate(ev["visitor_id"]))
                tagged += 1
    with open(dst, "w") as f:
        for ev in rows:
            f.write(json.dumps(ev) + "\n")
    return tagged, total


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="canonical JSONL to enrich")
    ap.add_argument("--out", help="output path (default: in place)")
    ap.add_argument("--store-id", help="only tag events for this store_id")
    args = ap.parse_args(argv)
    dst = args.out or args.src
    tagged, total = enrich(args.src, dst, args.store_id)
    print(f"enriched {tagged}/{total} visitors with best-effort demographics -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
