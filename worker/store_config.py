"""
Per-store detection config — the one place that makes the SAME pipeline work for
a new store. Maps each store's cameras to a funnel role, the staff uniform colour
to match, the canonical store_id, and each clip's wall-clock anchor.

Adding a store = adding an entry here (+ its zones in zones.json). Nothing in
detect.py / events.py / the converter is store-specific.

Uniform matching
----------------
Staff are identified by uniform colour (PDF §3.3). Store 1 staff wear black, so
the match is "dark AND desaturated"; Store 2 staff wear a pink shirt, matched by
an HSV hue band. ``uniform.uniform_fraction`` consumes these specs.

Store 2 caveat
--------------
The Store 2 clips are NOT time-synchronised across cameras (the on-screen clocks
differ: zone≈15:28, entry≈19:39), so cross-camera session linking is unreliable
there — Store 2 validates per-camera detection, the pink-uniform staff rule, and
the multi-store API. Cross-camera fusion is only meaningful for the synced
Store 1 footage. Anchor times below are read from each clip's on-screen clock.
"""

from __future__ import annotations

from typing import Dict, Optional

# OpenCV HSV ranges: H in 0–179, S/V in 0–255.
UNIFORM_BLACK = {"name": "black", "mode": "black"}      # low V AND low S
UNIFORM_PINK = {"name": "pink", "mode": "hsv", "lo": [150, 50, 60], "hi": [178, 255, 255]}


STORES: Dict[str, dict] = {
    "STORE_BLR_002": {  # Store 1 — Brigade Road (Bangalore); synced clips
        "footage_date": "2026-04-10",
        "uniform": UNIFORM_BLACK,
        "classifier": {
            "uniform_rule": "top_and_bottom",
            "uniform_threshold": 0.80,
            "uniform_min_dwell_s": 20.0,
        },
        "cameras": {
            "cam3": {"role": "entry", "start": "20:10:00"},
            "cam1": {"role": "floor", "start": "20:10:27"},
            "cam2": {"role": "floor", "start": "20:10:02"},
            "cam5": {"role": "billing", "start": "20:09:48"},
        },
    },
    "STORE_BLR_009": {  # Store 2 — pink-uniform staff; clips NOT cross-synced
        "footage_date": "2026-03-29",
        "uniform": UNIFORM_PINK,
        "classifier": {
            "uniform_rule": "top_only",
            "uniform_threshold": 0.75,
            "uniform_min_dwell_s": 0.0,
        },
        "cameras": {
            "entry1": {"role": "entry", "start": "19:39:06"},
            "entry2": {"role": "entry", "start": "19:39:06"},
            "zone": {"role": "floor", "start": "15:27:51"},
            "billing": {"role": "billing", "start": "15:28:00"},
        },
    },
}


def get_store(store_id: str) -> dict:
    if store_id not in STORES:
        raise KeyError(f"unknown store_id {store_id!r}; known: {list(STORES)}")
    return STORES[store_id]


def uniform_spec(store_id: str) -> dict:
    return get_store(store_id)["uniform"]


def classifier_config(store_id: str) -> dict:
    return dict(get_store(store_id).get("classifier") or {})


def camera_role(store_id: str, camera: str) -> Optional[str]:
    cam = get_store(store_id)["cameras"].get(camera)
    return cam["role"] if cam else None


def camera_start(store_id: str, camera: str) -> Optional[str]:
    cam = get_store(store_id)["cameras"].get(camera)
    return cam["start"] if cam else None


def cameras_for(store_id: str) -> Dict[str, dict]:
    return get_store(store_id)["cameras"]


def store_ids() -> list:
    return list(STORES.keys())
