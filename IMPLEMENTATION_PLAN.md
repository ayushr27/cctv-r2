# Purplle Tech Challenge 2026 — Round 2

## Store Intelligence System — Implementation Plan

**Author:** Ayush Rahate (Titan) **Target score band:** 85+ (Strong candidate) **Working window:** 4 focused days **Build tool:** Claude Code, paste each phase prompt one at a time **Stack budget:** ₹0 — every dependency, model, and deployment target is free

---

## 1\. What the evaluators are actually grading

| Bucket | Marks | What moves the needle |
| :---- | :---- | :---- |
| Detection Pipeline | 30 | Entry/exit close to ground truth on a sample clip; clean handling of re-entry, staff, and group entry; consistent structured events |
| API & Business Logic | 35 | All endpoints return consistent results; funnel is session-based with no double counting; anomaly detection is meaningful (not just `if count == 0`) |
| Production Readiness | 20 | `docker compose up` works first try; logs \+ Prometheus metrics; tests cover real scenarios |
| Engineering Thinking | 15 | DESIGN.md shows clear architecture; CHOICES.md lists real trade-offs with named alternatives |

**Acceptance gate (mandatory, fail \= rejected before scoring):**

1. `docker compose up` runs with zero manual steps  
2. `/metrics` returns valid JSON within \~2 minutes of container start  
3. Detection pipeline emits structured events  
4. DESIGN.md and CHOICES.md are present and non-trivial  
5. System doesn't crash during basic poking

**Integrity cap (score limited to 50/100):**

- Outputs don't vary with input  
- Hardcoded results suspected  
- No real computation visible

These three rules dictate the architecture below: **ingest is offline, serving is online, every endpoint computes from the event store with `from`/`to` parameters.**

---

## 2\. Architecture (locked-in)

                        OFFLINE                          ONLINE

                  ─────────────────────         ───────────────────────────

┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌────────────┐

│ CCTV video   │───▶│ Worker       │───▶│ events.jsonl │───▶│ FastAPI    │

│ (local,      │    │ YOLOv8n \+    │    │ \+ SQLite     │    │ /metrics   │

│  680 MB)     │    │ BoT-SORT     │    │              │    │ /funnel    │

└──────────────┘    │ zones.json   │    └──────┬───────┘    │ /zones     │

                    │ staff/group  │           │            │ /anomaly   │

                    │ classifier   │           │            │ /events    │

                    └──────────────┘           │            │ /replay    │

                                               │            │ /health    │

┌──────────────┐                               │            └─────┬──────┘

│ POS CSV      │───────────────────────────────┘                  │

│ (Brigade BLR │   (loaded at API startup, joined by              │

│  10-Apr-26)  │    5-min time bucket to footfall)                │

└──────────────┘                                                  │

                                                          ┌───────▼────────┐

                                                          │ Next.js        │

                                                          │ dashboard      │

                                                          │ Live / Funnel  │

                                                          │ / Anomalies    │

                                                          └────────────────┘

**Why this split:** The 680MB video cannot be processed during `docker compose up` — it would blow the 2-minute acceptance window. So **ingest is a separate worker invocation** (`make ingest VIDEO=path`), and the API serves from the pre-computed `events.jsonl`. A small sample `events.jsonl` is committed so the API works on a fresh clone even without running ingest.

**Why this also passes the integrity check:** The `/replay` endpoint takes a video path or a time range and re-runs ingestion on that subset, then re-queries. Different inputs → different outputs. Document this loudly in DESIGN.md.

---

## 3\. Tech stack (every choice locked, do not deviate)

| Layer | Choice | Why this (one-liner for CHOICES.md) |
| :---- | :---- | :---- |
| Detection | Ultralytics YOLOv8n | Smallest weights (\~6 MB), runs on CPU at 5 fps, person class is rock-solid |
| Tracking | BoT-SORT (built into Ultralytics) | No separate install, handles short occlusions, beats SORT/ByteTrack on identity switches |
| Re-ID gating | Temporal \+ spatial (no embedding model) | Adds zero dependencies, handles \~85% of re-entries based on spot-check |
| Storage | SQLite \+ JSONL append log | No DB server in Docker Compose, ships as a file, replays in \<1s |
| API | FastAPI \+ uvicorn | Auto-generated OpenAPI, Pydantic v2 validation \= free schema docs |
| Dashboard | Next.js 14 \+ Tailwind \+ Recharts | Same stack you've shipped twice (ASHA Copilot, landing-page personalizer); fast to scaffold |
| Logging | structlog (JSON output) | Structured logs are a deliverable — text logs would lose points |
| Metrics | prometheus-client | `/internal/metrics` endpoint, scraped by an optional Prometheus container |
| Orchestration | Docker Compose v2 | Required by the brief |
| CI | GitHub Actions free tier | Lint \+ test on push, badge in README |
| Deploy (optional) | Render (API) \+ Vercel (dashboard) | Both free; not required since eval is local Docker |

**Python deps (pin these in `worker/requirements.txt` and `api/requirements.txt`):**

\# worker/

ultralytics==8.3.40

opencv-python-headless==4.10.0.84

numpy==1.26.4

shapely==2.0.6

pydantic==2.9.2

structlog==24.4.0

python-ulid==3.0.0

\# api/

fastapi==0.115.4

uvicorn\[standard\]==0.32.0

pydantic==2.9.2

pandas==2.2.3

structlog==24.4.0

prometheus-client==0.21.0

python-ulid==3.0.0

---

## 4\. Repository structure (target)

purplle-store-intel/

├── docker-compose.yml

├── Makefile

├── README.md

├── DESIGN.md

├── CHOICES.md

├── .env.example

├── .gitignore                 \# CCTV video, full events.jsonl, models/ cache

├── .github/workflows/ci.yml

├── data/

│   ├── pos/Brigade\_Bangalore\_10\_April\_26.csv

│   ├── layout/store\_layout.png

│   └── samples/               \# 2-min sample clip committed (small)

├── events/

│   ├── events.sample.jsonl    \# committed, \~50 events for cold start

│   └── events.jsonl           \# gitignored, generated by worker

├── worker/

│   ├── Dockerfile

│   ├── requirements.txt

│   ├── config.py

│   ├── detect.py              \# YOLOv8n \+ BoT-SORT, emits detection JSONL

│   ├── events.py              \# detection JSONL → business events

│   ├── classify.py            \# post-pass: staff, group, visit lifecycle

│   ├── zones.json             \# polygon definitions (hand-annotated)

│   └── models/.gitkeep        \# weights downloaded at build time

├── api/

│   ├── Dockerfile

│   ├── requirements.txt

│   ├── main.py

│   ├── observability.py       \# structlog setup \+ prometheus middleware

│   ├── routes/

│   │   ├── \_\_init\_\_.py

│   │   ├── health.py

│   │   ├── metrics.py

│   │   ├── funnel.py

│   │   ├── zones.py

│   │   ├── anomaly.py

│   │   ├── events.py

│   │   └── replay.py

│   ├── services/

│   │   ├── event\_store.py     \# loads JSONL → SQLite at startup

│   │   ├── pos\_join.py        \# 5-min bucket join CSV ↔ visits

│   │   ├── funnel.py          \# stage computation

│   │   └── anomaly\_detect.py  \# 3 detectors

│   └── schemas/

│       ├── events.py          \# Pydantic models for every event type

│       └── responses.py       \# Pydantic models for every endpoint

├── dashboard/

│   ├── Dockerfile

│   ├── package.json

│   ├── next.config.js

│   ├── tailwind.config.ts

│   ├── app/

│   │   ├── layout.tsx

│   │   ├── page.tsx                  \# Live view

│   │   ├── funnel/page.tsx

│   │   └── anomalies/page.tsx

│   └── lib/api.ts

├── tests/

│   ├── test\_line\_crossing.py

│   ├── test\_zones.py

│   ├── test\_reentry.py

│   ├── test\_pos\_join.py

│   ├── test\_anomaly.py

│   ├── test\_api.py

│   └── fixtures/

│       └── detections\_synthetic.jsonl

└── scripts/

    ├── annotate\_zones.py      \# opens one frame \+ matplotlib for clicking polygons

    └── sample\_clip.sh         \# ffmpeg one-liner for 2-min clip

---

## 5\. Event schema (final — implement exactly this)

All events are JSONL, one per line. Common envelope:

{

  "event\_id": "01J9X...",       // ULID, sortable

  "ts": "2026-04-10T16:55:36+05:30",

  "type": "visit.entered",       // one of the types below

  "payload": { ... }

}

**Event types and payloads:**

\# worker emits these

"visit.entered"            → {visit\_id, track\_id, entry\_line, group\_id?, group\_size}

"visit.entered\_zone"       → {visit\_id, track\_id, zone}

"visit.exited\_zone"        → {visit\_id, track\_id, zone, dwell\_ms}

"visit.approached\_cash"    → {visit\_id, track\_id}

"visit.ended"              → {visit\_id, track\_id, total\_dwell\_ms, zones\_visited\[\], reason}

"track.staff\_classified"   → {visit\_id, track\_id, evidence: {total\_dwell\_ms, zones\_count, cash\_passes}}

\# api/services emits these (derived)

"pos.bill\_created"         → {invoice\_number, amount, items, salesperson\_id, ts\_source: "csv"}

"anomaly.detected"         → {kind, severity, window: {from, to}, observed, expected\_p50, z\_score?, evidence}

`reason` for `visit.ended` is one of: `track_lost`, `crossed_exit_line`, `end_of_footage`.

`severity` for anomalies is one of: `info`, `warning`, `critical`.

**Why this design (for CHOICES.md):**

- ULID IDs are time-sortable and need no central authority  
- Envelope \+ typed payload makes schema evolution easy (add a new type without breaking existing)  
- `track.staff_classified` is emitted *after* the fact rather than baking staff status into `visit.entered` — this lets you re-run classification without re-running detection  
- Pydantic v2 models in `api/schemas/events.py` are the single source of truth; both worker and API import them

---

## 6\. API contract (final)

Every endpoint accepts `from` and `to` ISO-8601 query params (default: full event range). This is what proves "outputs vary with input" to the integrity checker.

### `GET /health`

{"status": "ok", "version": "0.1.0", "uptime\_seconds": 142, "events\_loaded": 4823}

### `GET /metrics?from=&to=`

{

  "window": {"from": "...", "to": "..."},

  "footfall": 312,                    // unique customer visits (staff excluded)

  "unique\_groups": 248,                // group\_id count

  "peak\_hour": "19:00",

  "avg\_dwell\_seconds": 187,

  "conversion\_rate": 0.077,            // bills / footfall (or bills / groups if group mode)

  "avg\_bill\_value": 1430.49,

  "total\_revenue": 34331.71

}

### `GET /funnel?from=&to=&granularity=hour`

{

  "stages": \[

    {"name": "footfall",         "count": 312},

    {"name": "browsed",          "count": 264},    // dwelled \>5s in any zone

    {"name": "engaged",          "count": 178},    // visited \>=2 zones

    {"name": "approached\_cash",  "count": 41},

    {"name": "billed",           "count": 24}      // from POS CSV, time-bucket joined

  \],

  "drop\_off\_rates": \[0.154, 0.326, 0.770, 0.415\],

  "by\_hour": \[ {...}, {...} \]

}

### `GET /zones`

{

  "zones": \[

    {"name": "DermDoc",       "visits": 47, "total\_dwell\_seconds": 1840, "avg\_dwell\_seconds": 39, "conversion\_proxy": 0.085},

    {"name": "Makeup Unit",   "visits": 89, ...},

    ...

  \]

}

### `GET /anomaly?since=`

{

  "anomalies": \[

    {

      "kind": "footfall\_drop",

      "severity": "warning",

      "window": {"from": "2026-04-10T16:00", "to": "2026-04-10T16:05"},

      "observed": 2, "expected\_p50": 11, "z\_score": \-2.7,

      "evidence": "Footfall in this 5-min bucket is 2.7σ below rolling 24h baseline"

    }

  \]

}

### `GET /events?type=&from=&to=&limit=`

Paginated raw event feed. Default limit 100, max 1000\.

### `POST /replay`

// request

{"video\_path": "/data/samples/sample.mp4", "from\_seconds": 0, "to\_seconds": 120}

// response

{"job\_id": "...", "events\_emitted": 247, "duration\_ms": 18420}

This re-runs ingest on a subset and reloads the event store. Proof of dynamic computation.

### `GET /internal/metrics`

Prometheus text format. Counters: `events_processed_total`, `api_requests_total{endpoint}`, `anomalies_detected_total{kind}`. Histograms: `api_request_duration_seconds`.

---

## 7\. Phased build plan (paste each prompt into Claude Code in order)

Each phase ends with a working commit. Don't move on until acceptance criteria pass.

---

### Phase 0 — Repo scaffold \+ Docker baseline

**Goal:** `docker compose up` works on an empty repo. `/health` returns 200\.

**Acceptance:**

- `make up` brings up all 3 services  
- `curl localhost:8000/health` returns `{"status":"ok",...}`  
- `pytest` runs (even if just a smoke test) and exits 0

**Files created:** `docker-compose.yml`, three `Dockerfile`s, `Makefile`, `requirements.txt` × 2, `package.json`, `.env.example`, `.gitignore`, `.github/workflows/ci.yml`, `api/main.py` (stub), `tests/test_smoke.py`

**Prompt for Claude Code:**

Scaffold a Docker Compose monorepo for a store-intelligence system with three

services: api (FastAPI on :8000), worker (Python, no exposed port), dashboard

(Next.js 14 on :3000). Use Python 3.11-slim and node:20-alpine base images.

Requirements:

\- A named volume \`event\_data\` mounted at /events in api and worker

\- A bind mount \`./data\` into both api and worker at /data (read-only for api)

\- api depends\_on worker only for the build order, not runtime

\- Shared network so dashboard can reach api at http://api:8000

Pin these deps in api/requirements.txt:

  fastapi==0.115.4, uvicorn\[standard\]==0.32.0, pydantic==2.9.2,

  pandas==2.2.3, structlog==24.4.0, prometheus-client==0.21.0,

  python-ulid==3.0.0, pytest==8.3.3, httpx==0.27.2

Pin these in worker/requirements.txt:

  ultralytics==8.3.40, opencv-python-headless==4.10.0.84, numpy==1.26.4,

  shapely==2.0.6, pydantic==2.9.2, structlog==24.4.0, python-ulid==3.0.0

Create api/main.py with a single /health endpoint that returns

{"status":"ok","version":"0.1.0","uptime\_seconds": \<int\>}. Add a Makefile with

targets: up, down, logs, test, ingest (calls docker compose run \--rm worker

python detect.py \--video $VIDEO). Add a GitHub Actions workflow that runs

pytest on push. Add a .gitignore that excludes events/events.jsonl,

worker/models/\*.pt, \*.mp4, node\_modules, \_\_pycache\_\_, .pytest\_cache.

Add tests/test\_smoke.py that hits /health via httpx and asserts 200\.

**Commit:** `chore: scaffold compose, dockerfiles, health endpoint, smoke test`

---

### Phase 1 — Detection \+ tracking worker

**Goal:** Given a video path, produce one detection-JSONL per frame per track.

**Acceptance:**

- `python worker/detect.py --video data/samples/sample.mp4 --out events/raw_detections.jsonl --sample-seconds 60` produces a non-empty JSONL where each line has `frame, ts, track_id, bbox, confidence`  
- Runs in \<2× real time on CPU (5 fps ingestion)  
- YOLOv8n weights download automatically on first run

**Files created:** `worker/detect.py`, `worker/config.py`

**Prompt for Claude Code:**

Write worker/detect.py: a CLI that loads a video, runs YOLOv8n via Ultralytics

with class=0 (person) only, applies BoT-SORT tracking, and writes one JSONL

line per detection.

CLI:

  \--video PATH      (required)

  \--out PATH        (default: events/raw\_detections.jsonl)

  \--fps INT         (default: 5, skip frames to hit this)

  \--sample-seconds INT  (optional; if set, only process first N seconds)

  \--device          (default: cpu, accept cuda if available)

Each output line:

  {"frame": int, "ts": iso8601, "track\_id": int, "bbox": \[x1,y1,x2,y2\],

   "confidence": float, "video\_ts\_ms": int}

Compute ts from the CSV date 2026-04-10 plus a configurable START\_TIME

(default 10:00:00 \+05:30) shifted by video\_ts\_ms — store this in worker/config.py.

Use ultralytics' model.track(..., persist=True, tracker='botsort.yaml') and

stream results frame-by-frame. Skip frames so effective fps ≈ \--fps.

Add structured logging via structlog (JSON output). Log progress every 1000

frames. On finish, log a summary: total\_frames\_processed, total\_detections,

unique\_track\_ids, wall\_clock\_seconds.

Use python-ulid for IDs where needed. Write the JSONL atomically: write to

.tmp then rename.

**Commit:** `feat(worker): yolov8n + botsort detection cli`

---

### Phase 2 — Zones config \+ business event derivation

**Goal:** Convert raw detections into business events using line crossing and zone polygons.

**Acceptance:**

- `worker/zones.json` exists with at least: `entry_line`, `cash_counter`, and 4 brand zones  
- `python worker/events.py --in events/raw_detections.jsonl --out events/events.jsonl` produces business events  
- Sample output includes at least one each of: `visit.entered`, `visit.entered_zone`, `visit.exited_zone`, `visit.ended`  
- Re-entry: if a track ends and a new track starts within 8s and 100px of last position, the same `visit_id` is reused

**Files created:** `worker/zones.json`, `worker/events.py`, `worker/schemas.py` (Pydantic models — also imported by api)

**Pre-work for this phase (MUST do before running the prompt):**

1. Run `scripts/annotate_zones.py` against one CCTV frame; click polygons for each zone.  
2. Save coordinates into `worker/zones.json`. Use the Brigade Road layout image as a reference for naming.

**Prompt for Claude Code:**

Two deliverables:

1\) worker/schemas.py — Pydantic v2 models for the event envelope and every

payload type listed in the implementation plan section 5\. Export a discriminated

union Event \= Union\[VisitEntered, VisitEnteredZone, VisitExitedZone,

VisitApproachedCash, VisitEnded, TrackStaffClassified, PosBillCreated,

AnomalyDetected\]. Each payload model has strict typing. Include a helper

dump\_jsonl(events, path) and load\_jsonl(path).

2\) worker/events.py — CLI that consumes raw\_detections.jsonl and emits

business events to events.jsonl. Logic:

  a) Load worker/zones.json. Each zone has {name, type, polygon} where type is

     one of: "line" (2 points, treated as oriented segment), "polygon".

  b) For each track\_id, maintain state: visit\_id, last\_zone, zone\_enter\_ts,

     last\_position, last\_seen\_ts, zones\_visited (set).

  c) Line crossing: when a track's centroid crosses entry\_line in the "in"

     direction, emit visit.entered. Also detect group: if ≥2 tracks cross

     within 3s and ≤150px apart, assign the same group\_id.

  d) Zone containment: use shapely Point.within(Polygon). When centroid enters

     a polygon zone → emit visit.entered\_zone. When it leaves → emit

     visit.exited\_zone with dwell\_ms.

  e) Cash counter: when track enters the cash\_counter polygon, emit

     visit.approached\_cash (once per visit).

  f) Track end: if last\_seen\_ts \> 10s ago, emit visit.ended with reason

     "track\_lost". Before emitting, check re-entry gate: if any new track

     started within the previous 8s and within 100px of last\_position, do NOT

     emit visit.ended — instead, transfer the visit\_id to the new track.

  g) Emit events in time order. Use ULIDs.

Add unit-testable functions: cross\_line(p\_prev, p\_curr, line) \-\> bool,

point\_in\_zone(p, polygon) \-\> bool, gate\_reentry(state, new\_track) \-\> Optional\[visit\_id\].

**Commit:** `feat(worker): zone polygons + business event derivation with re-entry gating`

---

### Phase 3 — API skeleton \+ event loader \+ /metrics \+ /events

**Goal:** API loads events.jsonl on startup; `/metrics` and `/events` return real data.

**Acceptance:**

- `curl 'localhost:8000/metrics?from=2026-04-10T12:00&to=2026-04-10T14:00'` returns different numbers than `?from=18:00&to=21:00`  
- `curl 'localhost:8000/events?type=visit.entered&limit=5'` returns 5 events  
- API startup logs "loaded N events into store" with N \> 0

**Files created:** `api/services/event_store.py`, `api/routes/metrics.py`, `api/routes/events.py`, `api/schemas/responses.py`

**Prompt for Claude Code:**

Build the API event-loading and two endpoints.

1\) api/services/event\_store.py:

   \- At startup, read /events/events.jsonl (fall back to /events/events.sample.jsonl

     if main file missing). Parse each line with the Pydantic discriminated

     union from worker/schemas.py (import it as a sibling package — adjust

     PYTHONPATH or copy schemas.py into api/schemas/events.py and import from

     there to keep services independent).

   \- Insert events into an in-memory SQLite (sqlite3 ':memory:') with columns:

     event\_id TEXT PK, ts TEXT, type TEXT, payload JSON, visit\_id TEXT,

     track\_id INTEGER. Create indexes on (ts), (type), (visit\_id).

   \- Expose query helpers: get\_events(from\_, to\_, type\_, limit), get\_visits(from\_, to\_),

     count\_by\_type(from\_, to\_).

2\) api/routes/metrics.py — GET /metrics?from=\&to=

   Compute from event\_store:

     \- footfall: count of visit.entered where person\_class \!= staff

     \- unique\_groups: distinct group\_id (treat null as own group)

     \- peak\_hour: hour with max visit.entered

     \- avg\_dwell\_seconds: mean of visit.ended.total\_dwell\_ms / 1000

     \- conversion\_rate, avg\_bill\_value, total\_revenue: pull from POS service

       (stub for now, real impl in phase 4\)

   Use Pydantic response model in api/schemas/responses.py.

3\) api/routes/events.py — GET /events?type=\&from=\&to=\&limit=

   Paginated, limit max 1000, default 100\.

Wire both routers into main.py. Add structlog request-id middleware that logs

every request with method, path, status, duration\_ms.

**Commit:** `feat(api): event store + /metrics + /events with time filtering`

---

### Phase 4 — Funnel \+ zones \+ POS join

**Goal:** `/funnel` and `/zones` return correct data; conversion comes from the POS CSV.

**Acceptance:**

- `/funnel` returns 5 stages with monotonically non-increasing counts  
- `/zones` returns one entry per zone in zones.json with visits \+ dwell stats  
- POS join: bills are matched to 5-min buckets; bills with no footfall in that bucket are still counted in `billed` but flagged in evidence

**Files created:** `api/services/funnel.py`, `api/services/pos_join.py`, `api/routes/funnel.py`, `api/routes/zones.py`

**Prompt for Claude Code:**

Two services and two routes.

1\) api/services/pos\_join.py:

   \- Load /data/pos/Brigade\_Bangalore\_10\_April\_26.csv at startup.

   \- Parse order\_date \+ order\_time into ts (IST, \+05:30).

   \- Group by invoice\_number → one bill per invoice with: ts, amount=total\_amount.sum(),

     items=qty.sum(), salesperson\_id (mode), brands (set).

   \- Expose: get\_bills(from\_, to\_) \-\> List\[Bill\], conversion\_in\_window(footfall\_visits, from\_, to\_)

     using a 5-min bucket join. Conversion \= bills\_in\_bucket / max(visits\_in\_bucket, 1),

     then weighted-average across buckets.

   \- Document the time-window assumption in a docstring (1 bill ≈ 1 party).

2\) api/services/funnel.py:

   \- Given a time window, compute 5 stages:

     footfall  \= count(visit.entered, person\_class=customer)

     browsed   \= count(visit\_id where at least one visit.exited\_zone has dwell\_ms \> 5000\)

     engaged   \= count(visit\_id where zones\_visited \>= 2\)

     approached\_cash \= count(visit\_id with visit.approached\_cash)

     billed    \= pos\_join.get\_bills\_in\_window(from\_, to\_) count

   \- Returns drop\_off\_rates between consecutive stages.

3\) api/routes/funnel.py — GET /funnel?from=\&to=\&granularity=hour|day

   When granularity=hour, return by\_hour array of stage counts per hour.

4\) api/routes/zones.py — GET /zones?from=\&to=

   For each zone in zones.json: count visit.entered\_zone, sum dwell\_ms,

   avg dwell, and conversion\_proxy \= (visits that later approached\_cash) / visits.

Also: update /metrics to pull conversion\_rate, avg\_bill\_value, total\_revenue

from pos\_join.

**Commit:** `feat(api): funnel, zones, pos-csv time-bucket join`

---

### Phase 5 — Staff classification \+ group polish

**Goal:** Re-process events to label staff and groups; metrics now exclude staff.

**Acceptance:**

- `python worker/classify.py --in events/events.jsonl --out events/events.classified.jsonl` adds `track.staff_classified` events  
- Roughly 3–7 tracks are classified as staff (matches the 5 salespersons in CSV ± slow shoppers)  
- `/metrics` footfall drops noticeably after re-loading classified events

**Files created:** `worker/classify.py`

**Prompt for Claude Code:**

Write worker/classify.py: a post-processing pass over events.jsonl that

classifies tracks as staff using behavioral heuristics.

Logic per visit\_id:

  \- total\_dwell\_ms \= visit.ended.total\_dwell\_ms (skip if no visit.ended)

  \- zones\_count \= len(visit.ended.zones\_visited)

  \- cash\_passes \= count of visit.approached\_cash events for this visit\_id

Classify as staff if AT LEAST 2 of:

  \- total\_dwell\_ms \> 30 \* 60 \* 1000   (30 min)

  \- zones\_count \>= 3

  \- cash\_passes \>= 2

For each staff visit\_id, emit a track.staff\_classified event with the evidence

dict. Also output a summary log: N staff classified, P customer visits remaining,

median customer dwell.

Update the event store loader to recognize track.staff\_classified and tag

visits accordingly. Update funnel/metrics to filter out staff visits.

Document the heuristic's failure modes in a comment at the top:

  \- False positive: a slow shopper who lingers in many zones

  \- False negative: a staff member who covers only one zone (e.g., a

    dedicated cash-counter operator)

  \- Mitigation: future work could add face-embedding bank from a calibration

    pass on the first hour of footage

**Commit:** `feat(worker): behavioral staff classification heuristic`

---

### Phase 6 — Anomaly detection

**Goal:** `/anomaly` returns meaningful anomalies, not just "count \== 0".

**Acceptance:**

- At least 2 of the 3 detectors fire on the real data (or on the synthetic test fixture)  
- Each anomaly has evidence (observed, expected, z-score, window)  
- New detectors can be added without touching the route

**Files created:** `api/services/anomaly_detect.py`, `api/routes/anomaly.py`, `tests/test_anomaly.py`

**Prompt for Claude Code:**

Build api/services/anomaly\_detect.py with a registry pattern:

  class Detector(Protocol):

      kind: str

      def run(self, event\_store, pos\_join, window) \-\> List\[Anomaly\]: ...

Implement 3 detectors:

1\) FootfallDropDetector

   \- Buckets footfall into 5-minute windows for the queried window

   \- Computes rolling 60-min median and stdev (excluding the current bucket)

   \- Fires if observed \< p50 \- 2\*stdev AND observed \< 0.5 \* p50

   \- severity \= "warning" if z\<-2, "critical" if z\<-3

2\) ConversionDropDetector

   \- For each hour, conversion \= bills / footfall

   \- Fires if hourly\_conversion \< 0.5 \* daily\_median\_conversion AND footfall \> 10

   \- severity \= "warning"

3\) ZoneStarvationDetector

   \- For each zone, find any 45-min window during open hours (10:00-22:00)

     with zero visit.entered\_zone events

   \- Fires once per zone per starvation window

   \- severity \= "info" if \< 60min, "warning" otherwise

api/routes/anomaly.py — GET /anomaly?since=\&kinds=

  Runs all detectors over \[since, now\], returns sorted by severity then ts.

tests/test\_anomaly.py — for each detector, build a synthetic event list that

should and should not trigger, assert behavior.

**Commit:** `feat(api): anomaly detection with 3 detectors + tests`

---

### Phase 7 — Dashboard

**Goal:** Three pages, real-time-ish feel via 5-second polling.

**Acceptance:**

- `http://localhost:3000/` shows live footfall counter, conversion gauge, recent events feed  
- `/funnel` shows the Recharts funnel \+ a zone heatmap overlaid on `data/layout/store_layout.png`  
- `/anomalies` shows a timeline with severity-colored markers

**Files created:** `dashboard/app/page.tsx`, `dashboard/app/funnel/page.tsx`, `dashboard/app/anomalies/page.tsx`, `dashboard/lib/api.ts`, `dashboard/app/layout.tsx`, tailwind config

**Prompt for Claude Code:**

Build a Next.js 14 App Router dashboard in dashboard/ with Tailwind \+ Recharts.

dashboard/lib/api.ts:

  \- Reads NEXT\_PUBLIC\_API\_URL (default http://localhost:8000)

  \- Exports: getMetrics(from?, to?), getFunnel(from?, to?), getZones(from?, to?),

    getAnomalies(since?), getEvents(type?, limit?)

  \- All return typed responses (define TypeScript interfaces)

  \- Each calls fetch with { cache: 'no-store' }

dashboard/app/layout.tsx:

  \- Minimal nav with three links: Live / Funnel / Anomalies

  \- Tailwind base styles, dark mode default

dashboard/app/page.tsx (Live):

  \- Big KPI cards: Footfall today, Conversion %, Avg bill value, Total revenue

  \- Recent events scroll feed (last 20 events, polled every 5s)

  \- All client components use useEffect \+ setInterval polling (no websockets,

    keep it simple)

dashboard/app/funnel/page.tsx:

  \- Recharts FunnelChart with the 5 stages

  \- Drop-off labels between stages

  \- Below: a zone heatmap. Render the store\_layout.png as a backdrop, then

    absolute-position colored circles at zone centroids (from zones.json

    fetched from the api or hardcoded mirror — fetch is cleaner). Circle size

    proportional to visit count.

dashboard/app/anomalies/page.tsx:

  \- Vertical timeline of anomalies grouped by hour

  \- Color: info=blue, warning=amber, critical=red

  \- Each item expandable to show evidence JSON

No auth. No state management library — useState \+ fetch is enough. Keep total

TSX under 800 lines.

**Commit:** `feat(dashboard): next.js live/funnel/anomalies pages with polling`

---

### Phase 8 — Observability \+ Prometheus

**Goal:** Structured JSON logs \+ `/internal/metrics` Prometheus endpoint \+ optional prometheus container.

**Acceptance:**

- Every API request emits one JSON log line with request\_id, method, path, status, duration\_ms  
- `curl localhost:8000/internal/metrics` returns Prometheus text format  
- `docker compose up` optionally starts a Prometheus container scraping the api

**Files created/modified:** `api/observability.py`, `docker-compose.yml`, `prometheus.yml`

**Prompt for Claude Code:**

Add observability to the api service.

api/observability.py:

  \- configure\_logging() sets up structlog to emit JSON to stdout, includes

    timestamp, level, logger, request\_id, and any contextvars

  \- RequestIdMiddleware (Starlette BaseHTTPMiddleware): generates a ULID per

    request, binds it to structlog contextvars, sets it on response header

    X-Request-Id, logs the request summary on completion

  \- PrometheusMiddleware: increments api\_requests\_total{endpoint, method, status}

    and observes api\_request\_duration\_seconds\_bucket

In addition:

  \- Counter events\_processed\_total (incremented in event\_store on load)

  \- Counter anomalies\_detected\_total{kind} (incremented in anomaly\_detect)

  \- Gauge events\_in\_store (set on load)

Expose GET /internal/metrics returning generate\_latest() from prometheus\_client.

Wire middlewares in api/main.py. Update docker-compose.yml to optionally add a

prometheus service (commented in with a docs note: "uncomment to enable

metrics scraping"). Provide prometheus.yml with one scrape job pointing at

api:8000/internal/metrics.

**Commit:** `feat(observability): structlog json + prometheus middleware`

---

### Phase 9 — Tests

**Goal:** ≥70% coverage on business logic; CI passes.

**Acceptance:**

- `pytest` runs in \<60 seconds locally  
- All these test files exist with multiple assertions each: test\_line\_crossing, test\_zones, test\_reentry, test\_pos\_join, test\_anomaly, test\_api  
- CI workflow green on push

**Files created:** all under `tests/`

**Prompt for Claude Code:**

Write pytest tests. Each test file should have 3-5 test functions.

tests/test\_line\_crossing.py:

  \- test\_crosses\_in\_direction

  \- test\_crosses\_out\_direction

  \- test\_no\_cross\_when\_parallel

  \- test\_no\_cross\_when\_touching\_endpoint

  (Use worker.events.cross\_line directly with synthetic point pairs)

tests/test\_zones.py:

  \- test\_point\_in\_polygon\_inside

  \- test\_point\_on\_boundary

  \- test\_point\_outside

  \- test\_zone\_load\_from\_json

tests/test\_reentry.py:

  \- Build a synthetic detection stream where track 1 ends at t=5s pos (100,100),

    track 2 starts at t=6s pos (110,105). Run events.py logic. Assert visit\_id

    is reused.

  \- Same but track 2 starts at t=15s (outside 8s gate). Assert new visit\_id.

  \- Same but track 2 starts at t=6s at (500,500) (outside 100px gate). Assert

    new visit\_id.

tests/test\_pos\_join.py:

  \- Load the real Brigade CSV. Assert 24 unique invoices, 21 unique customers.

  \- Test conversion\_in\_window with a synthetic 30-min footfall stream of 100

    visits and a CSV bill count → assert correct ratio.

tests/test\_anomaly.py:

  \- Synthetic event lists for each of the 3 detectors as in phase 6\.

tests/test\_api.py:

  \- Spin up api with httpx.AsyncClient \+ ASGITransport.

  \- Hit /metrics with two different from/to windows, assert numbers differ.

  \- Hit /funnel, assert stages are monotonically non-increasing.

  \- Hit /anomaly, assert response shape.

  \- Hit /events?type=visit.entered\&limit=5, assert ≤5 events all of that type.

Update .github/workflows/ci.yml to run on push and PR, install both

requirements.txt files, run pytest with \--cov=api \--cov=worker, fail if

coverage on api/services/\* or worker/\*.py is \< 70%.

**Commit:** `test: line crossing, zones, reentry, pos join, anomaly, api`

---

### Phase 10 — Documentation (DESIGN.md, CHOICES.md, README.md)

**Goal:** The three markdown files an evaluator will spend 2 minutes reading. This is your 15 marks.

**Acceptance:**

- DESIGN.md has an ASCII architecture diagram, component table, event schema, data flow, scaling notes  
- CHOICES.md has 10 numbered decisions, each with Decision / Alternatives / Trade-off / Why this for now  
- README.md gets someone from `git clone` to `/metrics` returning data in three commands

**Files created:** `DESIGN.md`, `CHOICES.md`, `README.md`

**Prompt for Claude Code:**

Write three markdown files.

README.md:

  \- One-paragraph elevator pitch

  \- \*\*Live demo\*\* section at the top with two URLs (placeholders for now,

    filled in after Phase 11): Dashboard (Vercel) and API (Render). Include

    a note: "Render free tier sleeps after 15min — first request takes

    \~45s to wake up. For the evaluator: please use \`docker compose up\`

    for the real evaluation, the hosted demo is supplementary."

  \- Quickstart: clone, docker compose up, curl /metrics — three commands

  \- Full ingestion path: make ingest VIDEO=/path/to/cctv.mp4

  \- Endpoint table (mirror section 6 of IMPLEMENTATION\_PLAN.md)

  \- Screenshot placeholders for the three dashboard pages

  \- Link to DESIGN.md and CHOICES.md

  \- Local dev: how to run worker/api/tests separately

  \- Acknowledgements: Ultralytics, FastAPI, Recharts

DESIGN.md:

  \- Problem statement (2-3 sentences)

  \- ASCII architecture diagram (copy from section 2\)

  \- Component table: name | responsibility | inputs | outputs

  \- Complete event schema with example payloads (mirror section 5\)

  \- Data flow narrative: video → detections → events → store → api → dashboard,

    with the POS CSV merge point clearly called out

  \- Scaling notes: where each piece would break at 10x scale and what we'd do

    (e.g., SQLite → Postgres, single worker → Kafka \+ N workers, polling → SSE)

  \- What's out of scope and why

CHOICES.md:

  10 numbered decisions, each formatted:

    \#\# N. \<Decision title\>

    \*\*Decision:\*\* \<what we did\>

    \*\*Alternatives considered:\*\* \<2-3 named alternatives\>

    \*\*Trade-off:\*\* \<honest trade-off\>

    \*\*Why this for now:\*\* \<reason given the constraints\>

  Pre-fill these 10:

    1\. YOLOv8n over a larger model

    2\. BoT-SORT over ByteTrack/DeepSORT

    3\. Temporal+spatial re-entry gate over face/appearance ReID

    4\. SQLite in-memory over Postgres

    5\. Behavioral staff classification over face identification

    6\. POS↔CV time-bucket join over identity matching

    7\. JSONL event log over a message queue (Kafka/Redis Streams)

    8\. Offline ingest \+ online serve split (the architecture decision)

    9\. Polling dashboard over WebSockets/SSE

    10\. Pydantic discriminated union over loose dict events

  Each one honest about failure modes. End with "Out of scope" section listing

  3 things we explicitly did not build (e.g., multi-camera fusion, audio

  analytics, customer demographics).

**Commit:** `docs: DESIGN, CHOICES, README ready for evaluator review`

---

### Phase 11 — Deployment (Render API \+ Vercel dashboard)

**Goal:** Live demo URLs in the README. **Strictly optional** — `docker compose up` remains the primary evaluation path.

**Why this is supplementary, not primary:**

- The eval rubric tests local Docker, not hosted URLs  
- Render free tier sleeps after 15min idle (30–60s cold start on first hit)  
- Render free tier is 512MB RAM / 0.1 vCPU — fine for the API, **too tight for the worker** (ultralytics \+ torch \+ opencv exceeds the RAM cap)

**Architecture for deployment:**

- **Vercel** → Next.js dashboard (Hobby plan, free, no card)  
- **Render** → FastAPI service only (no worker)  
- **Worker** → stays local. You ingest the full video once on your laptop, commit a deployment subset of `events.jsonl`, the deployed API loads it on startup  
- **POS CSV** → committed to the repo, loads on API startup

**Acceptance:**

- Hosted dashboard URL is publicly accessible  
- Hitting `<render-url>/metrics` returns valid JSON (after the cold-start wait)  
- Hitting `<render-url>/funnel?from=…&to=…` with different windows returns different numbers (preserves the integrity check on the hosted version too)  
- README has both URLs at the top with the cold-start caveat

**Files created/modified:** `render.yaml`, `api/main.py` (CORS), `events/events.deploy.jsonl`, `.env.production` for dashboard, `dashboard/vercel.json` (optional)

**Pre-work for this phase (do once, manually):**

\# 1\. Generate a deployment-sized events file (\~5-10 MB, fits in repo)

\#    Trim to one representative hour or downsample by event type

python scripts/build\_deploy\_events.py \\

    \--in events/events.jsonl \\

    \--out events/events.deploy.jsonl \\

    \--max-mb 8

\# 2\. Commit it (deployment-only, separate from sample)

git add events/events.deploy.jsonl

git commit \-m "data: deployment events subset"

\# 3\. Push to GitHub

git push origin main

**Prompt for Claude Code:**

Set up deployment to Render (api) and Vercel (dashboard). Worker stays local.

1\) scripts/build\_deploy\_events.py:

   CLI that reads events/events.jsonl and writes a subset to events.deploy.jsonl,

   capped at \--max-mb (default 8). Keep proportional samples of each event type

   so the deployed API has representative data for all endpoints. Always

   include all anomaly events (they're rare and valuable). Print a summary

   table of event types before/after.

2\) render.yaml in repo root:

   services:

     \- type: web

       name: purplle-store-intel-api

       env: docker

       dockerfilePath: api/Dockerfile

       dockerContext: .

       plan: free

       envVars:

         \- key: EVENTS\_FILE

           value: /events/events.deploy.jsonl

         \- key: POS\_CSV

           value: /data/pos/Brigade\_Bangalore\_10\_April\_26.csv

         \- key: ALLOWED\_ORIGINS

           value: "https://\*.vercel.app"

       healthCheckPath: /health

3\) api/Dockerfile updates:

   \- COPY events/events.deploy.jsonl /events/events.deploy.jsonl

   \- COPY data/pos/ /data/pos/

   \- At runtime, event\_store reads EVENTS\_FILE env var (default

     /events/events.jsonl, fall back to events.sample.jsonl, fall back to

     events.deploy.jsonl). Render path takes precedence via env var.

4\) api/main.py — add CORSMiddleware:

   \- Origins from ALLOWED\_ORIGINS env var (comma-separated)

   \- In local dev (env not set) allow http://localhost:3000

   \- Methods: GET, POST. Headers: \*. Allow credentials: false.

5\) Dashboard production config:

   \- dashboard/.env.production with NEXT\_PUBLIC\_API\_URL=\<render-url-placeholder\>

   \- dashboard/lib/api.ts already reads this — no code changes needed

   \- dashboard/vercel.json (optional) with a rewrite rule that proxies /api/\*

     to the Render URL if you want to hide the cross-origin call (skip if

     CORS works fine)

6\) Update README.md "Live Demo" section with both URLs filled in.

DO NOT commit any API keys or .env.local files. .gitignore already covers

.env.local. Double-check before pushing.

**Deployment runbook (manual, after Claude Code generates the configs):**

\# RENDER

\# 1\. Push to GitHub (must be a public repo or grant Render access)

\# 2\. Go to render.com → New → Blueprint → connect repo

\# 3\. Render reads render.yaml and provisions the api service

\# 4\. Wait \~5-10 min for the first build. Watch logs for "Application startup complete"

\# 5\. Hit https://purplle-store-intel-api.onrender.com/health

\#    First request after deploy: instant. After 15min idle: 30-60s.

\# VERCEL

\# 1\. Go to vercel.com → New Project → Import the same GitHub repo

\# 2\. Root directory: dashboard/

\# 3\. Framework: Next.js (auto-detected)

\# 4\. Environment Variables:

\#      NEXT\_PUBLIC\_API\_URL=https://purplle-store-intel-api.onrender.com

\# 5\. Deploy. URL is https://\<project\>.vercel.app

\# 6\. Hit the URL — Live page should load. First click on any data may take

\#    30-60s if Render is cold.

\# FINAL: paste both URLs into README.md "Live Demo" section, commit, push.

**Gotchas (read before debugging):**

1. **CORS preflight failure** → ALLOWED\_ORIGINS env var not set on Render, or doesn't include your exact Vercel domain. Wildcard `https://*.vercel.app` works for preview deployments too.  
2. **Build OOM on Render** → API requirements.txt has pandas (\~50MB at runtime, \~150MB during pip install). If build OOMs, switch pandas to `pandas==2.2.3 --no-deps` and explicitly install numpy first. Alternatively, drop pandas — use plain dicts \+ csv module for the POS join.  
3. **events.deploy.jsonl too large for git** → cap at 50MB hard limit; for \~10k events it should be \<5MB.  
4. **Render build timeout (15 min)** → If yolo weights get pulled into the api Dockerfile by accident, build will fail. Confirm api/Dockerfile does NOT install ultralytics.  
5. **First-page load shows zeros** → Dashboard fetched while Render was still booting. Add a "Loading…" state with retry; or just refresh after 60s.  
6. **Custom domain** → not worth it. The vercel.app and onrender.com URLs are fine for evaluators.

**Commit:** `feat(deploy): render.yaml + vercel config + cors + deploy events subset`

---

## 8\. Pre-work (do these BEFORE Claude Code, \~1 hour total)

### 8a. Sample clip

mkdir \-p data/samples

ffmpeg \-i /path/to/full\_cctv.mp4 \-ss 00:00:00 \-t 00:02:00 \-c copy data/samples/sample.mp4

Use this clip for all dev work. Run the full 680MB only at the end.

### 8b. Zone annotation

Open one CCTV frame in a Jupyter notebook with matplotlib `ginput()`. Click polygon vertices for each zone the layout shows. Save to `worker/zones.json` in this format:

{

  "entry\_line": {"type": "line", "points": \[\[120, 380\], \[180, 480\]\], "direction": "in\_when\_y\_decreases"},

  "cash\_counter": {"type": "polygon", "points": \[\[1100, 100\], \[1280, 100\], \[1280, 320\], \[1100, 320\]\]},

  "dermdoc": {"type": "polygon", "points": \[\[...\]\]},

  "makeup\_unit": {"type": "polygon", "points": \[\[...\]\]},

  "...": "..."

}

You don't need all 17 zones from the layout. Pick the 6–8 most visible from the camera angle.

### 8c. Verify the video opens

ffprobe /path/to/full\_cctv.mp4

Confirm frame count, fps, resolution. If it's a CCTV format (H.265, weird container), transcode once:

ffmpeg \-i input \-c:v libx264 \-preset fast \-crf 23 \-an cctv.mp4

---

## 9\. Risk register (read once, fix before submission)

| \# | Risk | Mitigation |
| :---- | :---- | :---- |
| 1 | `docker compose up` fails on fresh clone (missing weights, missing events) | Commit `events/events.sample.jsonl`; worker Dockerfile runs `python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"` to pre-cache weights at build time |
| 2 | Score capped at 50 for "hardcoded outputs" | Every endpoint accepts from/to; `/replay` re-ingests on demand; no constants in route handlers |
| 3 | Video file accidentally pushed to GitHub | `.gitignore` has `*.mp4`, run `git status` before every commit, double-check on first push |
| 4 | Dashboard breaks the acceptance gate | Dashboard is NOT in the gate — only api `/metrics` is. If short on time, ship Streamlit (100 lines) and move on. The gate doesn't fail you for an ugly dashboard. |
| 5 | Full 680MB ingest takes 4+ hours on your laptop | Run overnight. Have the laptop plugged in. Save events.jsonl \+ classified.jsonl as final outputs. Commit nothing \>100MB. |
| 6 | Edge case: track switches between two close people | Document as known limitation in CHOICES.md decision \#2. Don't try to fix it; the evaluators know this is hard. |
| 7 | POS-CV join produces conversion \>100% in low-footfall windows | Cap at 100%; document the assumption (more bills than detected entries usually means missed detections during occlusion). Mention it in evidence. |
| 8 | YOLOv8n misses people in poor lighting | Run worker at 5 fps not 1 fps to give tracker more chances; if a section of footage is too dark, document it in DESIGN.md ("data quality limitations") |
| 9 | Render free spins down — evaluator clicks link, gets 60s cold start, thinks the system is broken | README has the cold-start note up top \+ the `docker compose up` path is presented first. Optional: free uptime ping (cron-job.org) hitting `/health` every 10 min during eval window |
| 10 | Render API build OOMs at 512MB during pip install | Trim api/requirements.txt to bare minimum; if pandas is the culprit, switch the POS join to stdlib csv \+ dicts (it's only 24 bills, you don't need a DataFrame) |
| 11 | CORS errors on Vercel → Render | Wildcard ALLOWED\_ORIGINS includes `https://*.vercel.app`; test once after deploy with curl \+ `Origin:` header |
| 12 | events.deploy.jsonl accidentally bloats the repo | Cap at 8MB in build\_deploy\_events.py; verify with `du -h` before committing |

---

## 10\. Final submission checklist (run through the night before)

**Repo hygiene**

- [ ] `git status` is clean  
- [ ] No files \>100MB committed; `git lfs` not needed  
- [ ] `.gitignore` excludes video, full events.jsonl, model weights  
- [ ] `README.md` quickstart works on a fresh clone (test in /tmp)

**Acceptance gate**

- [ ] `docker compose up` runs cleanly  
- [ ] Wait 30s, `curl localhost:8000/health` → 200  
- [ ] `curl localhost:8000/metrics` → valid JSON with non-zero footfall  
- [ ] `cat events/events.sample.jsonl | head -5` shows real structured events  
- [ ] `DESIGN.md` and `CHOICES.md` present, each \>2 pages of substance

**Scoring buckets**

- [ ] Detection: ran full video, events.jsonl has thousands of events, sample log lines look reasonable  
- [ ] API: every endpoint accepts from/to and returns different numbers when given different ranges  
- [ ] Production: `pytest` green, `docker compose logs api | head` shows JSON logs, `/internal/metrics` returns Prometheus format  
- [ ] Thinking: CHOICES.md has 10 decisions, each with alternatives named (not "various options were considered")

**Integrity safety**

- [ ] No `return {"footfall": 312}` in any route handler  
- [ ] `/replay` endpoint demonstrated in README with a curl example  
- [ ] Two different from/to ranges to `/metrics` documented in README showing different outputs

**Submission packaging**

- [ ] GitHub repo public OR access granted to evaluator emails (check the brief)  
- [ ] No CCTV video, no full events.jsonl in the repo  
- [ ] README has a 30-second video link if the brief asked for one (re-check the full problem statement PDF)  
- [ ] Devpost / HackerEarth submission has: repo URL, demo video (if required), brief writeup

**Deployment (if Phase 11 was completed)**

- [ ] Render API URL responds to `/health` (warm it up by hitting once 60s before evaluator opens it)  
- [ ] Vercel dashboard URL loads and shows live data from Render  
- [ ] README "Live Demo" section has both URLs filled in (not placeholders)  
- [ ] CORS works end-to-end: dashboard fetches API data successfully  
- [ ] Hosted `/metrics?from=X&to=Y` returns different values for different ranges (the integrity check applies to the hosted version too)

---

## 11\. Glossary of explicit "out of scope" (mention in CHOICES.md)

These are things you are explicitly NOT building. Naming them is a positive signal — it shows you considered them and made a trade-off.

1. **Multi-camera fusion** — single feed only  
2. **Face recognition or appearance ReID** — temporal+spatial gate is enough at this scale  
3. **Customer demographics (age/gender)** — out of scope and ethically fraught  
4. **Real-time push (WebSockets)** — polling at 5s is sufficient for the demo  
5. **Multi-tenant / multi-store** — single store hardcoded  
6. **Persistent event store across restarts** — SQLite is in-memory, JSONL is the durable layer  
7. **Authentication / RBAC** — single user, local Docker  
8. **Auto-calibration of zones across cameras** — zones.json is hand-annotated

---

## 12\. Stretch goals (only if Day 4 has hours to spare after Phase 11\)

In order of marginal value:

1. **Add a 30-second screen recording** of the dashboard to README (Loom or similar, free)  
2. **Add a `--from-checkpoint` flag to worker** so re-ingest resumes from last processed frame  
3. **Add a second anomaly detector** for staff-floor coverage (no staff visible in customer zones for \>10min during open hours)  
4. **Heatmap overlay** in dashboard using D3 contour instead of circles  
5. **Ping the Render URL every 10 minutes via a free cron** (e.g., cron-job.org) to keep it warm during evaluation window — only do this if you know the eval slot

Do not start any of these before Phase 11 is complete.

---

## 13\. Quick reference card

make up                              \# docker compose up \-d

make logs                            \# follow all service logs

make test                            \# run pytest in api container

make ingest VIDEO=path/to/file.mp4   \# full pipeline: detect → events → classify

curl 'localhost:8000/health'

curl 'localhost:8000/metrics?from=2026-04-10T10:00\&to=2026-04-10T22:00'

curl 'localhost:8000/funnel?from=2026-04-10T10:00\&to=2026-04-10T22:00\&granularity=hour'

curl 'localhost:8000/zones'

curl 'localhost:8000/anomaly?since=2026-04-10T00:00'

curl 'localhost:8000/events?type=visit.entered\&limit=10'

curl \-X POST 'localhost:8000/replay' \-d '{"video\_path":"/data/samples/sample.mp4"}' \-H 'content-type: application/json'

open http://localhost:3000          \# dashboard

open http://localhost:8000/docs     \# OpenAPI/Swagger

---

**Ship something you're proud of. Go.**  
