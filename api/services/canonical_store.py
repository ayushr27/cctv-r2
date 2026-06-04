"""
Canonical event store — the live, ingest-driven store behind the PDF contract.

Separate from the legacy ``event_store.py`` (which holds dotted ``visit.*``
events for the original dashboard). This one holds canonical PDF-schema events
(schemas/canonical.py), is written by ``POST /events/ingest``, and is read by
the ``/stores/{id}/*`` intelligence endpoints.

Design
------
* In-memory SQLite, ``event_id`` PRIMARY KEY → ``INSERT OR IGNORE`` gives true
  idempotency (re-ingesting the same event is a no-op, counted as a duplicate).
* A committed canonical seed (``events/canonical.seed.jsonl``) is loaded at
  startup so a fresh clone answers ``GET /stores/STORE_BLR_002/metrics`` with
  real data without any ingest step.
* ``ingest()`` normalizes (ingest_normalize) then validates (CANONICAL_ADAPTER)
  each row independently — a bad row is reported, never aborts the batch.
* If the connection was never built, queries raise ``StoreUnavailable`` so the
  route layer can return a structured HTTP 503 (graceful degradation).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import structlog

from schemas.canonical import CANONICAL_ADAPTER, to_dict

logger = structlog.get_logger()


class StoreUnavailable(RuntimeError):
    """Raised when the store is queried before it was loaded (→ HTTP 503)."""


def _seed_candidates() -> List[str]:
    env = os.environ.get("CANONICAL_EVENTS_FILE")
    paths = [env] if env else []
    paths += [
        "/events/canonical.seed.jsonl",
        "events/canonical.seed.jsonl",
    ]
    return [p for p in paths if p]


def parse_utc_ms(value: str) -> int:
    """ISO-8601 → epoch ms. Trailing 'Z' and naive strings are treated as UTC."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _ms_to_iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


# A query for one of these store ids means "all stores" (cumulative view) — the
# store_id filter is dropped so reads union across every ingested store.
ALL_STORES = frozenset({"ALL", "*", "all"})


def is_all_stores(store_id: Optional[str]) -> bool:
    return store_id in ALL_STORES


class CanonicalStore:
    def __init__(self) -> None:
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self.loaded = 0
        self.seed_source: Optional[str] = None
        # {store_id: {camera: {peak, distinct, visitors}}} — the fragmentation-aware
        # footfall summary written by scripts/occupancy.py per detection run.
        self.occupancy_by_store: Dict[str, dict] = {}

    # -- lifecycle --------------------------------------------------------

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE canonical_events (
                event_id   TEXT PRIMARY KEY,
                store_id   TEXT NOT NULL,
                camera_id  TEXT,
                visitor_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                ts_ms      INTEGER NOT NULL,
                ts_iso     TEXT NOT NULL,
                zone_id    TEXT,
                dwell_ms   INTEGER NOT NULL DEFAULT 0,
                is_staff   INTEGER NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 1.0,
                metadata   TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute("CREATE INDEX idx_can_store_ts ON canonical_events(store_id, ts_ms)")
        conn.execute("CREATE INDEX idx_can_type ON canonical_events(store_id, event_type)")
        conn.execute("CREATE INDEX idx_can_visitor ON canonical_events(store_id, visitor_id)")
        conn.commit()

    def load(self, seed_path: Optional[str] = None) -> int:
        """Build the DB and seed it from a committed canonical JSONL (if any)."""
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_schema(conn)
        with self._lock:
            old = self._conn
            self._conn = conn
            self.loaded = 0
            self.seed_source = None
        if old is not None:
            old.close()

        resolved = seed_path or next(
            (p for p in _seed_candidates() if Path(p).exists()), None
        )
        if resolved and Path(resolved).exists():
            with open(resolved) as f:
                batch = []
                for line in f:
                    line = line.strip()
                    if line:
                        batch.append(json.loads(line))
            result = self.ingest(batch)
            self.seed_source = resolved
            logger.info("canonical_seed_loaded", source=resolved, **result)
        else:
            logger.info("canonical_seed_absent", searched=_seed_candidates())

        # Also pick up any per-store pipeline outputs (run_pipeline.sh writes
        # <events>/<STORE_ID>/canonical.jsonl). Loading them here means a fresh
        # detection run — e.g. Store 2 — shows up on the next API start without
        # re-seeding; ingest() is idempotent so overlap with the seed is a no-op.
        import glob

        for extra in sorted(
            glob.glob("events/STORE_*/canonical.jsonl")
            + glob.glob("/events/STORE_*/canonical.jsonl")
        ):
            if resolved and Path(extra).resolve() == Path(resolved).resolve():
                continue
            try:
                with open(extra) as f:
                    batch = [json.loads(line) for line in f if line.strip()]
                r = self.ingest(batch)
                logger.info("canonical_output_loaded", source=extra, **r)
            except Exception as exc:  # noqa: BLE001 — a bad pipeline file must not break startup
                logger.warning("canonical_output_skip", source=extra, error=str(exc))

        self._load_occupancy()
        return self.loaded

    def _load_occupancy(self) -> None:
        """Load each store's occupancy.json (peak + de-fragmented visitor counts)."""
        import glob
        import re

        found: Dict[str, dict] = {}
        for path in sorted(
            glob.glob("events/STORE_*/occupancy.json")
            + glob.glob("/events/STORE_*/occupancy.json")
        ):
            m = re.search(r"(STORE_[A-Za-z0-9_]+)/occupancy\.json$", path)
            if not m:
                continue
            try:
                with open(path) as f:
                    found[m.group(1)] = json.load(f)
                logger.info("occupancy_loaded", source=path, cameras=len(found[m.group(1)]))
            except Exception as exc:  # noqa: BLE001 — a bad summary must not break startup
                logger.warning("occupancy_skip", source=path, error=str(exc))
        self.occupancy_by_store = found

    def occupancy(self, store_id: Optional[str] = None) -> Dict[str, Dict[str, dict]]:
        """
        {store_id: {camera: {peak, distinct, visitors}}}. For a concrete store,
        just that store's cameras; for ALL/None, every store's summary (the
        intelligence layer sums each store's busiest camera, never across stores).
        """
        if store_id is None or is_all_stores(store_id):
            return dict(self.occupancy_by_store)
        sub = self.occupancy_by_store.get(store_id)
        return {store_id: sub} if sub else {}

    # -- ingest -----------------------------------------------------------

    def ingest(self, raw_events: Sequence[dict]) -> Dict[str, object]:
        """
        Normalize + validate + insert a batch. Idempotent by event_id. Returns a
        structured summary: accepted / duplicates / rejected[{index,error}].
        A malformed row is rejected individually; the batch never raises.
        """
        # Imported here (not at module top) to avoid any import cycle and to keep
        # the store usable even if a future normalizer import is heavy.
        from services.ingest_normalize import normalize_event

        if self._conn is None:
            raise StoreUnavailable("canonical store not loaded")

        accepted = 0
        duplicates = 0
        rejected: List[dict] = []
        rows: List[tuple] = []

        for i, raw in enumerate(raw_events):
            try:
                norm = normalize_event(raw)
                ev = CANONICAL_ADAPTER.validate_python(norm)
                d = to_dict(ev)
                rows.append(
                    (
                        d["event_id"],
                        d["store_id"],
                        d["camera_id"],
                        d["visitor_id"],
                        d["event_type"],
                        parse_utc_ms(d["timestamp"]),
                        d["timestamp"],
                        d.get("zone_id"),
                        int(d.get("dwell_ms") or 0),
                        1 if d.get("is_staff") else 0,
                        float(d.get("confidence") if d.get("confidence") is not None else 1.0),
                        json.dumps(d.get("metadata") or {}),
                    )
                )
            except Exception as exc:  # noqa: BLE001 — per-row partial success
                rejected.append({"index": i, "error": str(exc)})

        if rows:
            with self._lock:
                cur = self._conn.cursor()
                for r in rows:
                    cur.execute(
                        "INSERT OR IGNORE INTO canonical_events "
                        "(event_id, store_id, camera_id, visitor_id, event_type, "
                        " ts_ms, ts_iso, zone_id, dwell_ms, is_staff, confidence, metadata) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        r,
                    )
                    if cur.rowcount == 1:
                        accepted += 1
                    else:
                        duplicates += 1
                self._conn.commit()
                self.loaded = self._conn.execute(
                    "SELECT COUNT(*) FROM canonical_events"
                ).fetchone()[0]

        return {
            "received": len(raw_events),
            "accepted": accepted,
            "duplicates": duplicates,
            "rejected": rejected,
        }

    # -- queries ----------------------------------------------------------

    def _require(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StoreUnavailable("canonical store not loaded")
        return self._conn

    def fetch(
        self,
        store_id: str,
        from_: Optional[str] = None,
        to_: Optional[str] = None,
        types: Optional[Sequence[str]] = None,
    ) -> List[dict]:
        """
        Time-ordered canonical events for a store/window (optionally typed).
        A store_id of ``ALL``/``*`` (see ``is_all_stores``) drops the store filter
        and unions across every ingested store — the cumulative dashboard view.
        """
        conn = self._require()
        clauses: list = []
        params: list = []
        if store_id and not is_all_stores(store_id):
            clauses.append("store_id = ?")
            params.append(store_id)
        if from_:
            clauses.append("ts_ms >= ?")
            params.append(parse_utc_ms(from_))
        if to_:
            clauses.append("ts_ms <= ?")
            params.append(parse_utc_ms(to_))
        if types:
            placeholders = ",".join("?" for _ in types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(types)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT event_id, store_id, camera_id, visitor_id, event_type, ts_ms, "
            "ts_iso, zone_id, dwell_ms, is_staff, confidence, metadata "
            f"FROM canonical_events{where} "
            "ORDER BY ts_ms ASC, event_id ASC"
        )
        with self._lock:
            cur = conn.execute(sql, params)
            cols = [c[0] for c in cur.description]
            out = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["is_staff"] = bool(d["is_staff"])
                d["metadata"] = json.loads(d["metadata"]) if d["metadata"] else {}
                out.append(d)
        return out

    def stores(self) -> List[str]:
        conn = self._require()
        with self._lock:
            cur = conn.execute("SELECT DISTINCT store_id FROM canonical_events ORDER BY store_id")
            return [r[0] for r in cur.fetchall()]

    def last_ts_per_store(self) -> Dict[str, str]:
        """{store_id: latest event ISO ts} — drives /health STALE_FEED."""
        conn = self._require()
        with self._lock:
            cur = conn.execute(
                "SELECT store_id, MAX(ts_ms) FROM canonical_events GROUP BY store_id"
            )
            return {r[0]: _ms_to_iso(r[1]) for r in cur.fetchall()}

    def data_range(self, store_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        conn = self._require()
        sql = "SELECT MIN(ts_ms), MAX(ts_ms) FROM canonical_events"
        params: list = []
        if store_id and not is_all_stores(store_id):
            sql += " WHERE store_id = ?"
            params.append(store_id)
        with self._lock:
            lo, hi = conn.execute(sql, params).fetchone()
        return _ms_to_iso(lo), _ms_to_iso(hi)


# Module-level singleton — initialized by api/main.py at startup.
canonical_store = CanonicalStore()
