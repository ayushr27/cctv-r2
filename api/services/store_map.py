"""
Store registry — maps the API-facing canonical ``store_id`` to its POS store id,
a human label, and its camera role assignment.

Why a mapping layer
-------------------
* The acceptance gate queries ``GET /stores/STORE_BLR_002/metrics``, but the POS
  export keys the same physical store as ``ST1008``. Conversion has to join the
  canonical store to its POS rows, so we keep an explicit alias here rather than
  renaming either dataset.
* Store 2 has footage + layout but NO POS export in the provided resources, so
  its ``pos_store_id`` is ``None`` → conversion is reported as unattributable
  (documented), not an error.

The API is otherwise store-agnostic: any ``store_id`` that has been ingested is
queryable even if it is not listed here (it just has no POS/label). This table
only adds POS-join + display niceties for the two stores we ship footage for.
"""

from __future__ import annotations

from typing import Dict, Optional

# canonical store_id -> descriptor
STORES: Dict[str, dict] = {
    "STORE_BLR_002": {
        "label": "Store 1 — Brigade Road (Bangalore)",
        "pos_store_id": "ST1008",
        "cameras": {
            "entry": ["cam3"],
            "floor": ["cam1", "cam2"],
            "billing": ["cam5"],
        },
    },
    "STORE_BLR_009": {
        "label": "Store 2",
        "pos_store_id": None,  # no POS export provided for Store 2
        "cameras": {
            "entry": ["entry1", "entry2"],
            "floor": ["zone"],
            "billing": ["billing"],
        },
    },
}

# Default store the legacy dashboard endpoints attribute to.
DEFAULT_STORE_ID = "STORE_BLR_002"


def label_for(store_id: str) -> str:
    return STORES.get(store_id, {}).get("label", store_id)


def pos_store_id(store_id: str) -> Optional[str]:
    """The POS key for a canonical store (None → no POS join available)."""
    return STORES.get(store_id, {}).get("pos_store_id")


def floor_cameras(store_id: str) -> list:
    """The store's floor (sales-area) cameras — the basis for occupancy/footfall.

    Entry/billing cameras see the same shoppers a second time, so footfall is
    read off the busiest single FLOOR camera. Empty list = unknown store (the
    caller then falls back to every camera it has data for).
    """
    return list(STORES.get(store_id, {}).get("cameras", {}).get("floor", []))


def known_store_ids() -> list:
    return list(STORES.keys())
