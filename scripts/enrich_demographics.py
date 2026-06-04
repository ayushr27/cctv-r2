#!/usr/bin/env python3
"""
Best-effort demographic enrichment for canonical events.

WHAT THIS IS (and is not)
-------------------------
The challenge footage is FACE-BLURRED, so face-based age/gender models cannot
run. ``worker/demographics.py`` ships the *real* path: a VLM (Anthropic Haiku)
prompted on the person crop's body/clothing cues, enabled with
``DEMOGRAPHICS_BACKEND=vlm`` + ``ANTHROPIC_API_KEY``. That path needs the raw
crops and an API key, which a CPU-only / offline demo box does not have.

This script is the **offline stand-in** for that backend: it attaches explicit
per-visitor labels from ``visitor_demographics.jsonl`` to the first event of each
distinct visitor. It is:
  * data-driven (one row per reviewed/model-labelled visitor);
  * idempotent (skips events that already carry ``gender_pred``);
  * flagged ``is_face_hidden=true`` on every event, like the real backend;
  * aggregate-only -- no identity is stored, the numbers are low-confidence.

Rows without a label are left as unknown. This avoids inventing a gender split
from a hash distribution while still preserving a reproducible offline demo.

Usage:
  enrich_demographics.py events/canonical.seed.jsonl              # in place
  enrich_demographics.py in.jsonl --out out.jsonl                 # to a new file
  enrich_demographics.py in.jsonl --store-id STORE_BLR_009        # one store only
  enrich_demographics.py in.jsonl --labels path/to/labels.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_DEMO_KEYS = {
    "gender_pred", "age_pred", "age_bucket", "is_face_hidden",
    "demographic_confidence", "demographic_source",
}


def _normalize_gender(value) -> str | None:
    if value is None:
        return None
    g = str(value).strip().lower()
    if g in {"f", "female", "woman", "women"}:
        return "F"
    if g in {"m", "male", "man", "men"}:
        return "M"
    if g in {"unknown", "unk", "u"}:
        return "unknown"
    return None


def _load_labels(path: str | None) -> dict[tuple[str, str], dict]:
    if not path or not Path(path).exists():
        return {}
    labels: dict[tuple[str, str], dict] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            store_id = row.get("store_id")
            visitor_id = row.get("visitor_id")
            if not store_id or not visitor_id:
                continue
            meta = {"is_face_hidden": True}
            gender = _normalize_gender(row.get("gender_pred"))
            if gender:
                meta["gender_pred"] = gender
            if row.get("age_pred") is not None:
                meta["age_pred"] = row["age_pred"]
            if row.get("age_bucket"):
                meta["age_bucket"] = row["age_bucket"]
            if row.get("confidence") is not None:
                meta["demographic_confidence"] = row["confidence"]
            if row.get("source"):
                meta["demographic_source"] = row["source"]
            labels[(str(store_id), str(visitor_id))] = meta
    return labels


def _default_labels_path(src: str) -> str | None:
    p = Path(src)
    candidate = p.parent / "visitor_demographics.jsonl"
    return str(candidate) if candidate.exists() else None


def enrich(
    src: str,
    dst: str,
    store_id: str | None = None,
    labels_path: str | None = None,
) -> tuple[int, int]:
    labels = _load_labels(labels_path or _default_labels_path(src))
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
            for k in _DEMO_KEYS:
                meta.pop(k, None)
            label = labels.get(key)
            if label:
                meta.update(label)
                tagged += 1
            else:
                meta["is_face_hidden"] = True
    with open(dst, "w") as f:
        for ev in rows:
            f.write(json.dumps(ev) + "\n")
    return tagged, total


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="canonical JSONL to enrich")
    ap.add_argument("--out", help="output path (default: in place)")
    ap.add_argument("--store-id", help="only tag events for this store_id")
    ap.add_argument("--labels", help="visitor_demographics.jsonl path")
    args = ap.parse_args(argv)
    dst = args.out or args.src
    tagged, total = enrich(args.src, dst, args.store_id, args.labels)
    print(f"enriched {tagged}/{total} visitors with video-derived demographics -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
