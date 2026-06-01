# DESIGN — Store Intelligence System

## Problem statement

A Purplle retail store (Brigade Road, Bangalore) has **5 fixed CCTV cameras** and a
point-of-sale (POS) export for a trading day. The system turns that raw footage +
sales data into store-intelligence metrics — footfall, zone engagement, a
conversion funnel, staff filtering, and anomaly detection — served over an API and
a live dashboard. The cameras cannot be moved or added; the design works with the
feeds as given.

---

## Architecture

```
        OFFLINE (ingest, run once per video)              ONLINE (serve, docker compose up)
   ────────────────────────────────────────────      ──────────────────────────────────────────

   ┌───────────────┐   per camera   ┌────────────┐    ┌──────────────┐      ┌────────────────┐
   │ CCTV  CAM 1-5 │───transcode───▶│  worker    │    │ events/      │      │  FastAPI       │
   │ (H.265, fixed)│   to H.264     │  detect.py │───▶│ events.jsonl │─────▶│  in-mem SQLite │
   └───────────────┘                │  (YOLOv8n  │    │ (+ .sample)  │      │                │
                                    │  + BoT-SORT)│    └──────────────┘      │  /metrics      │
                                    └─────┬──────┘            ▲              │  /funnel       │
                                          │ raw_camN.jsonl    │              │  /zones        │
                                          ▼                   │              │  /anomaly      │
                                    ┌────────────┐            │              │  /events       │
                                    │  events.py │────────────┘              │  /health       │
                                    │  (zones,   │  business events          │  /internal/    │
                                    │  re-entry) │  per camera, merged       │    metrics     │
                                    └─────┬──────┘                           └───────┬────────┘
                                          │                                          │
                                    ┌─────▼──────┐                                   │
                                    │ classify.py│  staff tagging                    │
                                    │ (behavioral)│ (track.staff_classified)         │
                                    └────────────┘                                   │
                                                                                     │
   ┌───────────────┐                                                                 │
   │ POS CSV        │──────────loaded at API startup, joined by──────────────────────┤
   │ (Brigade,      │           5-min time bucket to footfall                        │
   │  10-Apr-2026)  │                                                                ▼
   └───────────────┘                                                        ┌────────────────┐
                                                                            │ Next.js        │
                                                                            │ dashboard      │
                                                                            │ Live / Funnel  │
                                                                            │ / Anomalies    │
                                                                            │ (5s polling)   │
                                                                            └────────────────┘
```

**The key architectural split: ingest is offline, serving is online.** The CCTV
footage cannot be processed inside the 2-minute `docker compose up` acceptance
window (detection is CPU-bound). So detection/event-derivation is a separate
worker invocation (`make ingest`), and the API serves from a pre-computed
`events.jsonl`. A committed `events.sample.jsonl` (202 real events) ships in the
repo so the API returns real data on a fresh clone with no ingest step.

### Multi-camera by role (not single-feed)

The brief provides 5 fixed cameras with distinct coverage. Rather than pick one,
each camera is assigned the funnel stage it can actually observe, and the results
are **fused by 5-minute time bucket** — the same mechanism used for the POS join.
There is deliberately **no cross-camera identity matching** (re-ID): `visit_id`
chains only within a single camera.

Zone names and their brand mapping come from the official store floor plan
(`Brigade Road - Store layout.xlsx`): each zone is named after the real shelf
section (the_face_shop, dermdoc, faces_canada, alps_goodness, makeup_unit,
accessories, cash_counter) and carries the list of POS `brand_name` values
shelved there. This powers a **zone ↔ brand-sales join** in `/zones` (zone
footfall next to the revenue of the brands sold from that zone), and the every
brand maps to exactly one zone so zone revenue reconciles to the POS total.

| Camera | Real-world view              | Funnel role                         |
| :----- | :--------------------------- | :---------------------------------- |
| CAM 1  | Store interior (top brand wall) | Browse — the_face_shop / dermdoc / makeup_unit |
| CAM 2  | Store interior, diagonal (bottom wall) | Browse — faces_canada / alps_goodness |
| CAM 3  | Outside main entrance        | **Footfall** — entry-line crossings |
| CAM 4  | Store room                   | (no customers — omitted)            |
| CAM 5  | Entrance + billing counter   | **Cash approach** — cash_counter + accessories |

---

## Component table

| Component | Responsibility | Inputs | Outputs |
| :-------- | :------------- | :----- | :------ |
| `worker/detect.py` | Person detection + tracking | video file, `--camera`, `--fps` | `raw_camN.jsonl` (frame, ts, track_id, bbox, conf) |
| `worker/events.py` | Derive business events from detections | `raw_camN.jsonl`, camera-keyed `zones.json` | `events_camN.jsonl` (visit.* events) |
| `worker/classify.py` | Behavioral staff classification | merged `events.jsonl` | `track.staff_classified` events |
| `worker/schemas.py` | Pydantic v2 event models (source of truth) | — | typed `Event` discriminated union |
| `api/services/event_store.py` | Load JSONL → in-memory SQLite, time-filtered queries | `events.jsonl` | query helpers (events, visits, histograms) |
| `api/services/pos_join.py` | Parse POS CSV, 5-min bucket conversion | `Brigade_*.csv` | bills, revenue, conversion |
| `api/services/funnel.py` | 5-stage funnel computation | event store + POS | stages, drop-off rates |
| `api/services/anomaly_detect.py` | Pluggable detector registry (3 detectors) | event store + POS | anomalies w/ evidence |
| `api/routes/*` | HTTP endpoints (metrics/funnel/zones/anomaly/events) | query params | JSON responses |
| `api/observability.py` | Structured JSON logs + Prometheus middleware | requests | logs + `/internal/metrics` |
| `dashboard/` | Next.js 14 dashboard, 5s polling | API JSON | Live / Funnel / Anomalies pages |

---

## Event schema

All events are JSONL, one per line, sharing a common envelope:

```json
{
  "event_id": "01KT16S2DH...",          // ULID, time-sortable
  "ts": "2026-04-10T20:09:50.402000+05:30",
  "camera": "cam5",                       // which feed produced it (optional)
  "type": "visit.approached_cash",
  "payload": { ... }
}
```

**Worker-emitted types** (the `payload` shape per type):

```
visit.entered           {visit_id, track_id, entry_line, group_id?, group_size}
visit.entered_zone      {visit_id, track_id, zone}
visit.exited_zone       {visit_id, track_id, zone, dwell_ms}
visit.approached_cash   {visit_id, track_id}
visit.ended             {visit_id, track_id, total_dwell_ms, zones_visited[], reason}
track.staff_classified  {visit_id, track_id, evidence:{total_dwell_ms, zones_count, cash_passes}}
```

`reason` ∈ `track_lost | crossed_exit_line | end_of_footage`.

**API/derived types:**

```
pos.bill_created        {invoice_number, amount, items, salesperson_id, ts_source:"csv"}
anomaly.detected        {kind, severity, window:{from,to}, observed, expected_p50?, z_score?, evidence}
```

`severity` ∈ `info | warning | critical`. The Pydantic models in
`worker/schemas.py` are the single source of truth; the API mirrors them in
`api/schemas/events.py` to keep the two services independently deployable.

Example `visit.ended`:

```json
{
  "event_id": "01KT16S2DH0MXMMV5VSWG50CKS",
  "ts": "2026-04-10T20:09:50.602000+05:30",
  "camera": "cam5",
  "type": "visit.ended",
  "payload": {
    "visit_id": "01KT16S2DHBMPYB9999SDPK44D",
    "track_id": 1,
    "total_dwell_ms": 2602,
    "zones_visited": ["cash_counter"],
    "reason": "track_lost"
  }
}
```

---

## Data flow

1. **Video → detections.** `detect.py` runs YOLOv8n (person class only) + BoT-SORT
   on each camera's clip, writing one JSONL line per detection. Timestamps are
   anchored to the footage wall-clock via `--start-time` (read off each camera's
   on-screen clock).
2. **Detections → events.** `events.py` loads that camera's zone config from the
   camera-keyed `zones.json`, then derives business events: entry-line crossings
   (door cameras), zone enter/exit with dwell, cash approach, visit end, and
   temporal+spatial re-entry gating (same person under a new track id → same
   `visit_id`).
3. **Per-camera merge.** The `events_camN.jsonl` files are merged time-sorted into
   `events.jsonl`. `classify.py` then appends `track.staff_classified` events.
4. **Events → store.** At API startup, `event_store.py` parses every line through
   the Pydantic union into an in-memory SQLite DB (indexed on `ts_ms`, `type`,
   `visit_id`).
5. **POS merge point.** Independently, `pos_join.py` loads the POS CSV at startup
   and groups line-items into bills. **Conversion and revenue join CV footfall to
   POS bills by 5-minute time bucket** — there is no shared customer identity, so
   time is the only join axis (1 bill ≈ 1 paying party).
6. **Store + POS → API.** Every endpoint accepts `from`/`to` and computes live, so
   outputs vary with the query window (the integrity requirement).
7. **API → dashboard.** The Next.js dashboard polls the API every 5s.

---

## Scaling notes (where each piece breaks at 10×, and the fix)

| Piece | Breaks at scale because… | Fix |
| :---- | :----------------------- | :-- |
| In-memory SQLite | rebuilt on every boot; bounded by RAM | swap to **Postgres** (or DuckDB) with the same query helpers; the store interface is the seam |
| Single worker | one process, one video at a time | **N workers + a queue** (Kafka / Redis Streams); each consumes a camera/segment, writes events |
| JSONL append log | linear scan to rebuild; no compaction | partition by hour/camera; or move to an event store / object storage with manifest |
| 5s polling dashboard | N clients × every endpoint × 12/min | **Server-Sent Events** or WebSocket push from a single event tap |
| Time-bucket POS join | coarse; mis-attributes across busy buckets | per-lane camera at the till + soft identity association |
| Single store | one location hardcoded | tenant/store id on every event + partitioned queries |

---

## What's out of scope (and why)

- **Cross-camera identity / re-ID** — tracking the same shopper across CAM 1→3→5
  needs appearance embeddings and is error-prone at this scale; time-bucket fusion
  is sufficient for store-level metrics and adds zero dependencies. (See CHOICES #3, #6.)
- **Face recognition / demographics** — out of scope and ethically fraught; the
  system stores no biometric or PII data.
- **Real-time ingest** — detection is offline by design (see the architecture
  split); the API never blocks on video.
- **`detect.py` automated tests** — it requires OpenCV + the YOLO weights + a video
  and cannot run in lightweight CI; it is validated by running the real pipeline.
  All other business logic is unit-tested (43 tests, ≥78% coverage).

> **Data-scale caveat (read this).** The provided CCTV clips are short samples
> (~2–3 minutes, all around 20:09–20:12 IST) while the POS CSV spans the full
> trading day (12:15–21:39). They barely overlap in time, so a default-window
> conversion rate is near-zero **and that is correct, not a bug** — it is the
> honest consequence of a 3-minute CV sample against a full-day sales log. Every
> endpoint is built to produce the right numbers on longer footage without code
> changes; see CHOICES.md.
