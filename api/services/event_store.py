"""
Event store: loads the JSONL event log into an in-memory SQLite database at
startup and serves time-filtered queries.

Design notes
------------
* In-memory SQLite (`:memory:`) — no DB server in Docker Compose; the JSONL file
  is the durable layer, this is just a fast queryable index rebuilt on boot.
* Every row keeps both the original ISO-8601 `ts` (for display) and an integer
  `ts_ms` epoch (for unambiguous, index-friendly range filtering — string
  comparison breaks across mixed UTC offsets).
* A single shared connection guarded by a lock: we load once at startup, then
  serve concurrent read-only queries from uvicorn's threadpool.

The store is exposed as a module-level singleton ``store``; call
``store.load()`` once during app startup (see api/main.py).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from instrumentation import events_in_store, events_processed_total
from schemas.events import EVENT_ADAPTER

logger = structlog.get_logger()

IST = timezone(timedelta(hours=5, minutes=30))


# Resolution order for the event file. EVENTS_FILE wins (used by deployment),
# then the generated full log, then the committed cold-start sample. Both the
# container path (/events/...) and a local-dev relative path are tried.
def _candidate_paths() -> List[str]:
    env = os.environ.get("EVENTS_FILE")
    paths = [env] if env else []
    paths += [
        "/events/events.jsonl",
        "/events/events.sample.jsonl",
        "events/events.jsonl",
        "events/events.sample.jsonl",
    ]
    return [p for p in paths if p]


def parse_ts(value: Optional[str], *, default_tz=IST) -> Optional[int]:
    """
    Parse an ISO-8601 string to epoch milliseconds. A naive datetime (no offset)
    is assumed to be IST, since all footage/POS data is IST. Returns None for a
    None/empty input so callers can treat it as "unbounded".
    """
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return int(dt.timestamp() * 1000)


def _ms_to_iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=IST).isoformat()


class EventStore:
    def __init__(self) -> None:
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self.loaded = 0
        self.source: Optional[str] = None
        # visit_ids flagged staff by track.staff_classified events (Phase 5).
        self.staff_visit_ids: set = set()

    # -- lifecycle --------------------------------------------------------

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE events (
                event_id TEXT PRIMARY KEY,
                ts       TEXT NOT NULL,
                ts_ms    INTEGER NOT NULL,
                type     TEXT NOT NULL,
                camera   TEXT,
                payload  TEXT NOT NULL,
                visit_id TEXT,
                track_id INTEGER
            )
            """
        )
        conn.execute("CREATE INDEX idx_events_ts ON events(ts_ms)")
        conn.execute("CREATE INDEX idx_events_type ON events(type)")
        conn.execute("CREATE INDEX idx_events_visit ON events(visit_id)")
        conn.commit()

    def load(self, path: Optional[str] = None) -> int:
        """
        (Re)build the in-memory DB from a JSONL file. Resolves the first existing
        candidate path when ``path`` is not given. Each line is validated against
        the Pydantic discriminated union before insertion; malformed lines are
        logged and skipped rather than crashing startup. Returns rows loaded.
        """
        resolved = path or next((p for p in _candidate_paths() if Path(p).exists()), None)
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_schema(conn)

        loaded, skipped = 0, 0
        staff_ids: set = set()
        if resolved and Path(resolved).exists():
            with open(resolved) as f:
                rows = []
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                        EVENT_ADAPTER.validate_python(raw)  # schema gate
                    except Exception as exc:  # noqa: BLE001 - log & skip bad lines
                        skipped += 1
                        logger.warning("event_parse_skip", lineno=lineno, error=str(exc))
                        continue
                    payload = raw.get("payload", {})
                    if raw["type"] == "track.staff_classified" and payload.get("visit_id"):
                        staff_ids.add(payload["visit_id"])
                    rows.append(
                        (
                            raw["event_id"],
                            raw["ts"],
                            parse_ts(raw["ts"]),
                            raw["type"],
                            raw.get("camera"),
                            json.dumps(payload),
                            payload.get("visit_id"),
                            payload.get("track_id"),
                        )
                    )
                conn.executemany(
                    "INSERT OR REPLACE INTO events "
                    "(event_id, ts, ts_ms, type, camera, payload, visit_id, track_id) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    rows,
                )
                conn.commit()
                loaded = len(rows)

        with self._lock:
            old = self._conn
            self._conn = conn
            self.loaded = loaded
            self.source = resolved
            self.staff_visit_ids = staff_ids
        if old is not None:
            old.close()

        # Prometheus: total parsed across (re)loads + current gauge.
        events_processed_total.inc(loaded)
        events_in_store.set(loaded)

        logger.info("event_store_loaded", source=resolved, loaded=loaded,
                    skipped=skipped, staff_visits=len(staff_ids))
        return loaded

    # -- queries ----------------------------------------------------------

    def _where_window(self, from_ms: Optional[int], to_ms: Optional[int]) -> Tuple[str, list]:
        clauses, params = [], []
        if from_ms is not None:
            clauses.append("ts_ms >= ?")
            params.append(from_ms)
        if to_ms is not None:
            clauses.append("ts_ms <= ?")
            params.append(to_ms)
        return (" AND ".join(clauses) if clauses else "1=1"), params

    def get_events(
        self,
        from_: Optional[str] = None,
        to_: Optional[str] = None,
        type_: Optional[str] = None,
        limit: int = 100,
    ) -> List[dict]:
        """Return reconstructed event envelopes in time order, bounded by limit."""
        from_ms, to_ms = parse_ts(from_), parse_ts(to_)
        where, params = self._where_window(from_ms, to_ms)
        if type_:
            where += " AND type = ?"
            params.append(type_)
        sql = (
            f"SELECT event_id, ts, type, camera, payload FROM events "
            f"WHERE {where} ORDER BY ts_ms ASC, event_id ASC LIMIT ?"
        )
        params.append(limit)
        with self._lock:
            cur = self._conn.execute(sql, params)
            out = []
            for r in cur.fetchall():
                out.append(
                    {
                        "event_id": r[0],
                        "ts": r[1],
                        "type": r[2],
                        "camera": r[3],
                        "payload": json.loads(r[4]),
                    }
                )
        return out

    def count_by_type(self, from_: Optional[str] = None, to_: Optional[str] = None) -> Dict[str, int]:
        from_ms, to_ms = parse_ts(from_), parse_ts(to_)
        where, params = self._where_window(from_ms, to_ms)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT type, COUNT(*) FROM events WHERE {where} GROUP BY type", params
            )
            return {row[0]: row[1] for row in cur.fetchall()}

    def get_visits(self, from_: Optional[str] = None, to_: Optional[str] = None) -> List[dict]:
        """
        Completed visits in the window: the payloads of ``visit.ended`` events
        (they carry total_dwell_ms + zones_visited). One row per ended visit.
        """
        from_ms, to_ms = parse_ts(from_), parse_ts(to_)
        where, params = self._where_window(from_ms, to_ms)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT payload FROM events WHERE {where} AND type = 'visit.ended' "
                f"ORDER BY ts_ms ASC",
                params,
            )
            return [json.loads(r[0]) for r in cur.fetchall()]

    def get_payloads(
        self, type_: str, from_: Optional[str] = None, to_: Optional[str] = None
    ) -> List[dict]:
        """All payloads of a given event type within the window (time-ordered)."""
        from_ms, to_ms = parse_ts(from_), parse_ts(to_)
        where, params = self._where_window(from_ms, to_ms)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT payload FROM events WHERE {where} AND type = ? ORDER BY ts_ms ASC",
                params + [type_],
            )
            return [json.loads(r[0]) for r in cur.fetchall()]

    def hour_histogram(
        self, type_: str, from_: Optional[str] = None, to_: Optional[str] = None
    ) -> Dict[str, int]:
        """Count events of a type bucketed by IST hour label 'HH:00'."""
        from_ms, to_ms = parse_ts(from_), parse_ts(to_)
        where, params = self._where_window(from_ms, to_ms)
        out: Dict[str, int] = {}
        with self._lock:
            cur = self._conn.execute(
                f"SELECT ts_ms FROM events WHERE {where} AND type = ?", params + [type_]
            )
            for (ms,) in cur.fetchall():
                hour = datetime.fromtimestamp(ms / 1000, tz=IST).strftime("%H:00")
                out[hour] = out.get(hour, 0) + 1
        return out

    def data_range(self) -> Tuple[Optional[str], Optional[str]]:
        """ISO min/max ts across all loaded events (for echoing the default window)."""
        with self._lock:
            cur = self._conn.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM events")
            lo, hi = cur.fetchone()
        return _ms_to_iso(lo), _ms_to_iso(hi)


# Module-level singleton — initialized by api/main.py at startup.
store = EventStore()
