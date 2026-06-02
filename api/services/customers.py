"""
Customer segments — non-demographic, privacy-preserving.

Answers "who shops here and how" WITHOUT inferring protected attributes
(no gender/age — the POS has no such field and CV inference would be biased and
unreliable; see CHOICES). Uses only signals that actually exist:

  * shopping party  — solo vs group, from CV visit.entered group_size (staff
                      excluded). Footfall-window limited on short clips.
  * customers       — unique vs repeat purchasers, from POS customer_number.
  * basket          — items/bill, value/bill, single- vs multi-brand baskets.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional


def customer_segments(store, pos, from_: Optional[str] = None, to: Optional[str] = None) -> dict:
    staff = getattr(store, "staff_visit_ids", set())

    # --- shopping party (CV): solo vs group ---
    entered = [p for p in store.get_payloads("visit.entered", from_, to)
               if p.get("visit_id") not in staff]
    solo = sum(1 for p in entered if (p.get("group_size") or 1) <= 1)
    group = sum(1 for p in entered if (p.get("group_size") or 1) >= 2)
    party_total = solo + group

    # --- customers (POS): unique vs repeat ---
    bills = pos.get_bills(from_, to)
    cust_bills = Counter(b.customer_number for b in bills if b.customer_number)
    unique_customers = len(cust_bills)
    repeat_customers = sum(1 for _, n in cust_bills.items() if n > 1)

    # --- basket (POS) ---
    n = len(bills)
    avg_items = round(sum(b.items for b in bills) / n, 2) if n else 0.0
    avg_value = round(sum(b.amount for b in bills) / n, 2) if n else 0.0
    multi_brand = sum(1 for b in bills if len(b.brands) > 1)
    single_brand = sum(1 for b in bills if len(b.brands) == 1)
    avg_brands = round(sum(len(b.brands) for b in bills) / n, 2) if n else 0.0

    return {
        "shopping_party": {
            "solo": solo,
            "group": group,
            "group_rate": round(group / party_total, 3) if party_total else 0.0,
            "basis": "CV footfall (visit.entered group_size), staff excluded",
        },
        "customers": {
            "unique": unique_customers,
            "repeat": repeat_customers,
            "repeat_rate": round(repeat_customers / unique_customers, 3) if unique_customers else 0.0,
            "basis": "POS customer_number within the window",
        },
        "basket": {
            "bills": n,
            "avg_items_per_bill": avg_items,
            "avg_value_per_bill": avg_value,
            "single_brand_bills": single_brand,
            "multi_brand_bills": multi_brand,
            "avg_brands_per_bill": avg_brands,
        },
        "note": (
            "Non-demographic segments only — no gender/age is inferred or stored "
            "(POS has no such field; CV inference would be biased and unreliable). "
            "Shopping-party counts are limited by the short CV footfall window."
        ),
    }
