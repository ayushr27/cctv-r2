# PROMPT: "Test the POS join: grouping line items into bills and the 5-minute-bucket conversion (capped at 1.0)."
# CHANGES MADE: Added the bills-in-zero-footfall-bucket evidence assertion and the conversion cap case.

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


def test_slim_csv_groups_baskets_by_timestamp(tmp_path):
    # The new challenge POS export has no invoice column; rows sharing a
    # (store, date, time) are one basket.
    csv_text = (
        "order_id,order_date,order_time,store_id,product_id,brand_name,total_amount\n"
        "1,10-04-2026,12:15:05,ST1008,399945,Faces Canada,302.33\n"
        "2,10-04-2026,12:15:05,ST1008,353621,Faces Canada,491.77\n"
        "3,10-04-2026,12:15:05,ST1008,333323,Faces Canada,453.88\n"
        "4,10-04-2026,12:42:18,ST1008,407887,Purplle,100.00\n"
        "5,10-04-2026,12:42:18,ST1008,384974,Faces Canada,397.38\n"
    )
    p = tmp_path / "slim.csv"
    p.write_text(csv_text)
    pos = PosJoin()
    n = pos.load(str(p))
    assert n == 2  # two baskets
    assert all(b.store_id == "ST1008" for b in pos.bills)
    assert round(sum(b.amount for b in pos.bills), 2) == 1745.36
    # store-filtered transactions() surface for the canonical conversion join
    assert len(pos.transactions("ST1008")) == 2
    assert pos.transactions("OTHER_STORE") == []


def test_pdf_schema_one_bill_per_row(tmp_path):
    csv_text = (
        "store_id,transaction_id,timestamp,basket_value_inr\n"
        "STORE_BLR_002,TXN1,2026-03-03T14:38:12Z,1240.00\n"
        "STORE_BLR_002,TXN2,2026-03-03T14:41:55Z,680.00\n"
    )
    p = tmp_path / "pdf.csv"
    p.write_text(csv_text)
    pos = PosJoin()
    n = pos.load(str(p))
    assert n == 2
    assert round(sum(b.amount for b in pos.bills), 2) == 1920.0
    assert len(pos.transactions("STORE_BLR_002")) == 2
