"""
POS CSV join service.

Loads the Brigade Bangalore POS export at startup, groups line items into one
bill per invoice, and joins bills to CV footfall by 5-minute time bucket.

Why a time-bucket join (and not identity matching)?
----------------------------------------------------
The POS export has no camera/track id, and the CV pipeline has no customer
identity (no PII, by design). The only shared axis is *time*. We therefore
assume **1 bill ≈ 1 paying party** and attribute a bill to whatever footfall
occurred in the same 5-minute window. This is an approximation: a bill in a
bucket with zero detected footfall (common here — the CV clips are short
samples while the POS covers the full trading day) is still counted as a real
bill, but flagged in the conversion evidence as un-attributable.

Implementation note: we use the stdlib ``csv`` module, not pandas — there are
only 24 bills, and dropping the pandas dependency keeps the API image small
enough for the Render free tier (plan risk register #10).
"""

from __future__ import annotations

import csv
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

IST = timezone(timedelta(hours=5, minutes=30))
BUCKET_MS = 5 * 60 * 1000  # 5-minute buckets


def _candidate_paths() -> List[str]:
    env = os.environ.get("POS_CSV")
    paths = [env] if env else []
    paths += [
        # Rich 39-column Brigade export first (powers brand/zone breakdowns);
        "/data/pos/Brigade_Bangalore_10_April_26.csv",
        "data/pos/Brigade_Bangalore_10_April_26.csv",
        "Brigade_Bangalore_10_April_26.csv",
        # then the slim 7-column challenge export under resources/ as a fallback
        # (same store/day, fewer columns — load() autodetects the schema).
        "/data/pos/pos_transactions.csv",
        "data/pos/pos_transactions.csv",
        "resources/POS - sample transactionsb1e826f.csv",
    ]
    # Last resort: any CSV dropped into resources/ that looks like a POS export.
    try:
        import glob

        paths += sorted(glob.glob("resources/POS*.csv"))
    except Exception:  # noqa: BLE001
        pass
    # Final fallback: the committed SYNTHETIC fixture (fabricated rows, not the
    # licensed export) so CI / a fresh clone without the real CSV still loads POS
    # data. The licensed paths above always win when present (local / Docker).
    paths += [
        os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "pos_sample.csv"),
        "tests/fixtures/pos_sample.csv",
    ]
    return [p for p in paths if p]


def _parse_ts(order_date: str, order_time: str) -> Optional[datetime]:
    """order_date is DD-MM-YYYY, order_time is HH:MM:SS, both IST."""
    try:
        return datetime.strptime(
            f"{order_date.strip()} {order_time.strip()}", "%d-%m-%Y %H:%M:%S"
        ).replace(tzinfo=IST)
    except ValueError:
        return None


def _parse_iso_ms(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return int(dt.timestamp() * 1000)


def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


class Bill:
    __slots__ = ("invoice_number", "ts", "ts_ms", "amount", "items",
                 "salesperson_id", "brands", "customer_number", "store_id")

    def __init__(self, invoice_number, ts, amount, items, salesperson_id, brands,
                 customer_number="", store_id=""):
        self.invoice_number = invoice_number
        self.ts = ts                      # ISO-8601 string
        self.ts_ms = _parse_iso_ms(ts)
        self.amount = round(amount, 2)
        self.items = items
        self.salesperson_id = salesperson_id
        self.brands = sorted(brands)
        self.customer_number = customer_number  # for new-vs-returning segments
        self.store_id = store_id          # POS store key (e.g. ST1008)

    def as_dict(self) -> dict:
        return {
            "invoice_number": self.invoice_number,
            "ts": self.ts,
            "amount": self.amount,
            "items": self.items,
            "salesperson_id": self.salesperson_id,
            "brands": self.brands,
            "store_id": self.store_id,
        }


class PosJoin:
    def __init__(self) -> None:
        self.bills: List[Bill] = []
        self.source: Optional[str] = None
        # Per-line-item brand revenue records: (ts_ms, brand_name, amount).
        # Kept at line-item granularity (not per-invoice) so brand revenue is
        # accurate even when one bill spans multiple brands — used by the
        # zone<->brand sales join in /zones.
        self.brand_lines: List[tuple] = []

    # -- lifecycle --------------------------------------------------------

    def load(self, path: Optional[str] = None) -> int:
        resolved = path or next((p for p in _candidate_paths() if Path(p).exists()), None)
        bills: List[Bill] = []
        brand_lines: List[tuple] = []
        if resolved and Path(resolved).exists():
            with open(resolved, newline="") as f:
                reader = csv.DictReader(f)
                fields = set(reader.fieldnames or [])
                rows = list(reader)

            # Per-line brand revenue (when the CSV carries brand_name). Powers the
            # dashboard /brands + /zones joins; absent qty/product degrade to 0/"".
            for row in rows:
                brand = (row.get("brand_name") or "").strip()
                dt = self._row_dt(row, fields)
                if brand and dt is not None:
                    brand_lines.append((
                        int(dt.timestamp() * 1000),
                        brand,
                        _safe_float(row.get("total_amount") or row.get("basket_value_inr")),
                        _safe_int(row.get("qty") or 1),
                        (row.get("product_name") or "").strip(),
                    ))

            # Autodetect the POS schema by its columns (plan §3):
            if "invoice_number" in fields:
                bills = self._bills_by_invoice(rows)        # rich Brigade export
            elif "transaction_id" in fields:
                bills = self._bills_per_row(rows, fields)   # PDF pos_transactions
            else:
                bills = self._bills_by_timestamp(rows)      # slim challenge export

        bills.sort(key=lambda b: b.ts_ms or 0)
        self.bills = bills
        self.brand_lines = brand_lines
        self.source = resolved
        logger.info(
            "pos_loaded",
            source=resolved,
            bills=len(bills),
            stores=sorted({b.store_id for b in bills if b.store_id}),
            total_revenue=round(sum(b.amount for b in bills), 2),
        )
        return len(bills)

    # -- schema-specific bill builders -----------------------------------

    @staticmethod
    def _row_dt(row: dict, fields: set):
        """Parse a row timestamp across all three POS schemas (→ aware datetime)."""
        if "timestamp" in fields and row.get("timestamp"):
            ms = _parse_iso_ms(row["timestamp"])
            return datetime.fromtimestamp(ms / 1000, tz=IST) if ms is not None else None
        return _parse_ts(row.get("order_date", ""), row.get("order_time", ""))

    def _bills_by_invoice(self, rows: List[dict]) -> List[Bill]:
        """Rich export: group line items by invoice_number into one bill."""
        grouped: Dict[str, List[dict]] = defaultdict(list)
        for row in rows:
            inv = (row.get("invoice_number") or "").strip()
            if inv:
                grouped[inv].append(row)
        out: List[Bill] = []
        for inv, items in grouped.items():
            dts = [_parse_ts(r.get("order_date", ""), r.get("order_time", "")) for r in items]
            dts = [d for d in dts if d is not None]
            if not dts:
                continue
            ts = min(dts).isoformat()
            amount = sum(_safe_float(r.get("total_amount")) for r in items)
            qty = sum(_safe_int(r.get("qty")) for r in items)
            sp = Counter((r.get("salesperson_id") or "").strip() for r in items).most_common(1)[0][0]
            brands = {(r.get("brand_name") or "").strip() for r in items if r.get("brand_name")}
            cust = Counter((r.get("customer_number") or "").strip() for r in items).most_common(1)[0][0]
            store = (items[0].get("store_id") or "").strip()
            out.append(Bill(inv, ts, amount, qty, sp, brands, cust, store))
        return out

    def _bills_per_row(self, rows: List[dict], fields: set) -> List[Bill]:
        """PDF schema: one transaction per row (transaction_id, timestamp, basket_value_inr)."""
        out: List[Bill] = []
        for r in rows:
            dt = self._row_dt(r, fields)
            if dt is None:
                continue
            amount = _safe_float(r.get("basket_value_inr") or r.get("total_amount"))
            txn = (r.get("transaction_id") or r.get("order_id") or "").strip()
            store = (r.get("store_id") or "").strip()
            brands = {(r.get("brand_name") or "").strip()} - {""}
            out.append(Bill(txn, dt.isoformat(), amount, 1, "", brands, "", store))
        return out

    def _bills_by_timestamp(self, rows: List[dict]) -> List[Bill]:
        """
        Slim challenge export: no invoice column, so reconstruct baskets by
        grouping line items that share (store_id, order_date, order_time) — rows
        with an identical timestamp are one paying party (verified in the data).
        """
        grouped: Dict[tuple, List[dict]] = defaultdict(list)
        for r in rows:
            key = (
                (r.get("store_id") or "").strip(),
                (r.get("order_date") or "").strip(),
                (r.get("order_time") or "").strip(),
            )
            grouped[key].append(r)
        out: List[Bill] = []
        for (store, od, ot), items in grouped.items():
            dt = _parse_ts(od, ot)
            if dt is None:
                continue
            amount = sum(_safe_float(r.get("total_amount")) for r in items)
            brands = {(r.get("brand_name") or "").strip() for r in items if r.get("brand_name")}
            txn = f"{store}-{od}-{ot}"
            out.append(Bill(txn, dt.isoformat(), amount, len(items), "", brands, "", store))
        return out

    # -- queries ----------------------------------------------------------

    def get_bills(
        self,
        from_: Optional[str] = None,
        to_: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> List[Bill]:
        lo, hi = _parse_iso_ms(from_), _parse_iso_ms(to_)
        out = []
        for b in self.bills:
            if b.ts_ms is None:
                continue
            if store_id is not None and b.store_id != store_id:
                continue
            if lo is not None and b.ts_ms < lo:
                continue
            if hi is not None and b.ts_ms > hi:
                continue
            out.append(b)
        return out

    def transactions(
        self,
        store_id: Optional[str] = None,
        from_: Optional[str] = None,
        to_: Optional[str] = None,
    ) -> List[Tuple[int, float]]:
        """
        (ts_ms, basket_value) per bill for a store/window — the minimal POS
        surface the canonical ``/stores/{id}`` conversion join needs. A store
        with no POS rows (e.g. Store 2) returns ``[]`` → conversion 0, not error.
        """
        return [
            (b.ts_ms, b.amount)
            for b in self.get_bills(from_, to_, store_id)
            if b.ts_ms is not None
        ]

    def revenue_in_window(
        self, from_: Optional[str] = None, to_: Optional[str] = None
    ) -> Tuple[float, float, int]:
        """Return (total_revenue, avg_bill_value, bill_count) for the window."""
        bills = self.get_bills(from_, to_)
        n = len(bills)
        total = round(sum(b.amount for b in bills), 2)
        avg = round(total / n, 2) if n else 0.0
        return total, avg, n

    def brand_revenue_in_window(
        self, from_: Optional[str] = None, to_: Optional[str] = None
    ) -> Dict[str, float]:
        """{brand_name: total_amount} from line items within the window."""
        lo, hi = _parse_iso_ms(from_), _parse_iso_ms(to_)
        out: Dict[str, float] = defaultdict(float)
        for ts_ms, brand, amount, _qty, _product in self.brand_lines:
            if lo is not None and ts_ms < lo:
                continue
            if hi is not None and ts_ms > hi:
                continue
            out[brand] += amount
        return {b: round(v, 2) for b, v in out.items()}

    def brand_breakdown_in_window(
        self, from_: Optional[str] = None, to_: Optional[str] = None
    ) -> Dict[str, dict]:
        """
        Per brand within the window: {brand: {revenue, units, top_products}}.
        top_products is the [(product_name, units)] list (desc), aggregate POS
        sales — i.e. *what sells from that brand*, NOT linked to any individual.
        """
        lo, hi = _parse_iso_ms(from_), _parse_iso_ms(to_)
        rev: Dict[str, float] = defaultdict(float)
        units: Dict[str, int] = defaultdict(int)
        products: Dict[str, Counter] = defaultdict(Counter)
        for ts_ms, brand, amount, qty, product in self.brand_lines:
            if lo is not None and ts_ms < lo:
                continue
            if hi is not None and ts_ms > hi:
                continue
            rev[brand] += amount
            units[brand] += qty
            if product:
                products[brand][product] += qty
        out: Dict[str, dict] = {}
        for brand in rev:
            out[brand] = {
                "revenue": round(rev[brand], 2),
                "units": units[brand],
                "top_products": products[brand].most_common(3),
            }
        return out

    def data_range(self) -> Tuple[Optional[str], Optional[str]]:
        if not self.bills:
            return None, None
        return self.bills[0].ts, self.bills[-1].ts

    def conversion_in_window(
        self,
        footfall_visits: List[dict],
        from_: Optional[str] = None,
        to_: Optional[str] = None,
    ) -> dict:
        """
        Bucketed conversion = bills_in_bucket / max(visits_in_bucket, 1), then a
        visit-weighted average across buckets (buckets with more footfall count
        more). ``footfall_visits`` is a list of visit.entered payloads, each
        carrying a ``ts`` key (ISO-8601). Conversion is capped at 1.0 per bucket
        (more bills than detected entries = missed detections, not >100%
        conversion — plan risk #7).

        Returns the weighted rate plus evidence: bucket counts and how many
        bills landed in zero-footfall buckets.
        """
        lo, hi = _parse_iso_ms(from_), _parse_iso_ms(to_)

        def bucket(ms: int) -> int:
            return ms // BUCKET_MS

        visit_buckets: Dict[int, int] = defaultdict(int)
        for v in footfall_visits:
            ms = _parse_iso_ms(v.get("ts"))
            if ms is None:
                continue
            if lo is not None and ms < lo:
                continue
            if hi is not None and ms > hi:
                continue
            visit_buckets[bucket(ms)] += 1

        bill_buckets: Dict[int, int] = defaultdict(int)
        for b in self.get_bills(from_, to_):
            if b.ts_ms is not None:
                bill_buckets[bucket(b.ts_ms)] += 1

        total_visits = sum(visit_buckets.values())
        total_bills = sum(bill_buckets.values())
        bills_without_footfall = sum(
            n for bkt, n in bill_buckets.items() if visit_buckets.get(bkt, 0) == 0
        )

        # Visit-weighted conversion across buckets that had footfall.
        weighted_sum, weight = 0.0, 0
        for bkt, vis in visit_buckets.items():
            if vis <= 0:
                continue
            conv = min(bill_buckets.get(bkt, 0) / vis, 1.0)
            weighted_sum += conv * vis
            weight += vis
        weighted_conv = round(weighted_sum / weight, 4) if weight else 0.0

        return {
            "conversion_rate": weighted_conv,
            "total_visits": total_visits,
            "total_bills": total_bills,
            "bills_without_footfall": bills_without_footfall,
            "evidence": (
                f"{total_bills} bills vs {total_visits} detected visits across "
                f"{len(visit_buckets)} footfall buckets; {bills_without_footfall} "
                f"bills fell in 5-min buckets with no detected footfall "
                f"(short CV sample vs full-day POS) and are counted but unattributable."
            ),
        }


# Module-level singleton — initialized by api/main.py at startup.
pos = PosJoin()
