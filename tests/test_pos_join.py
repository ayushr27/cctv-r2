"""
Tests for the POS join service against the REAL Brigade Bangalore CSV.

Asserts the known invoice/customer counts and the 5-min-bucket conversion math
on a synthetic footfall stream.
"""

import csv
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from services.pos_join import PosJoin  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def _resolve(*rel, container):
    """Repo-relative path (CI layout) with a container-mount fallback."""
    p = os.path.join(os.path.dirname(__file__), "..", *rel)
    return p if os.path.exists(p) else container


CSV_PATH = _resolve(
    "data", "pos", "Brigade_Bangalore_10_April_26.csv",
    container="/data/pos/Brigade_Bangalore_10_April_26.csv",
)


def test_real_csv_invoice_and_customer_counts():
    pos = PosJoin()
    n = pos.load(CSV_PATH)
    # one Bill per invoice
    assert n == 24, f"expected 24 invoices, got {n}"
    assert len(pos.bills) == 24
    # 21 unique customers at the CSV (line-item) level
    with open(CSV_PATH, newline="") as f:
        customers = {row["customer_number"].strip() for row in csv.DictReader(f)}
    assert len(customers) == 21, f"expected 21 unique customers, got {len(customers)}"


def test_total_revenue_matches_known_value():
    pos = PosJoin()
    pos.load(CSV_PATH)
    total, avg, n = pos.revenue_in_window()
    assert n == 24
    assert round(total, 2) == 34331.71
    assert round(avg, 2) == round(34331.71 / 24, 2)


def test_get_bills_window_filter():
    pos = PosJoin()
    pos.load(CSV_PATH)
    # a 1-hour window must return fewer bills than the full day
    full = len(pos.get_bills())
    hour = len(pos.get_bills("2026-04-10T19:00:00+05:30", "2026-04-10T20:00:00+05:30"))
    assert 0 <= hour < full


def test_conversion_in_window_ratio():
    """100 footfall visits + the real bill count in the same buckets -> ratio."""
    pos = PosJoin()
    pos.load(CSV_PATH)
    # Synthetic 30-min footfall stream (all within 19:00-19:30) so visits land
    # in real POS buckets; conversion = bills/visits per bucket, visit-weighted,
    # capped at 1.0.
    base = datetime(2026, 4, 10, 19, 0, 0, tzinfo=IST)
    visits = [
        {"visit_id": f"v{i}", "ts": (base + timedelta(seconds=i * 18)).isoformat()}
        for i in range(100)
    ]
    res = pos.conversion_in_window(
        visits, "2026-04-10T19:00:00+05:30", "2026-04-10T19:30:00+05:30"
    )
    assert res["total_visits"] == 100
    assert 0.0 <= res["conversion_rate"] <= 1.0
    # 100 visits vs far fewer bills => conversion well under 1
    assert res["conversion_rate"] < 0.5
    assert "evidence" in res
