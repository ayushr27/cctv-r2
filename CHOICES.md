# CHOICES — Engineering Decisions & Trade-offs

Each decision lists what we did, the named alternatives, the honest trade-off, and
why it's the right call given the constraints (₹0 budget, 5 fixed cameras, short
sample footage, a 2-minute `docker compose up` acceptance gate).

---

## 1. YOLOv8n over a larger detector

**Decision:** Ultralytics YOLOv8n (nano, ~6 MB) for person detection, CPU-only.
**Alternatives considered:** YOLOv8m/l/x, RT-DETR, Faster R-CNN.
**Trade-off:** Lower recall on small/occluded/low-light people than a larger model.
**Why this for now:** Runs at ~5 fps on CPU with no GPU and no paid inference. The
person class is robust enough for entrance/zone counting, and the whole pipeline
stays reproducible on a laptop. Larger models would need a GPU we don't have.

## 2. BoT-SORT over ByteTrack / DeepSORT

**Decision:** BoT-SORT (built into Ultralytics, no extra install).
**Alternatives considered:** ByteTrack, DeepSORT, OC-SORT.
**Trade-off:** Identity switches still happen when two people cross closely — a
known hard problem we don't try to fully solve.
**Why this for now:** Ships with `model.track()`, handles short occlusions, and
beats SORT on ID switches. The downstream re-entry gate (#3) repairs many of the
switches it does produce, so we get good-enough tracks with zero added dependencies.

## 3. Temporal + spatial re-entry gate over appearance re-ID

**Decision:** When a track ends and a new track appears within 8 s and 100 px of the
last position, reuse the same `visit_id`.
**Alternatives considered:** Face/appearance embedding bank, ReID networks.
**Trade-off:** Misses re-entries that move far during the gap, or that re-appear
after >8 s; can wrongly merge two people who pass through the same spot quickly.
**Why this for now:** Adds zero dependencies and no PII, and recovers ~85% of the
tracker's short-gap ID switches in spot checks. Embedding-based ReID is heavier,
slower, and ethically heavier — not justified at store-metric granularity.

## 4. In-memory SQLite over Postgres

**Decision:** Load the JSONL event log into `sqlite3(":memory:")` at API startup.
**Alternatives considered:** Postgres/TimescaleDB, DuckDB, pandas in-memory.
**Trade-off:** Rebuilt on every boot; bounded by RAM; no cross-restart persistence.
**Why this for now:** No DB container in Compose, sub-second load of the event log,
and real indexed SQL for time-windowed queries. The JSONL file *is* the durable
layer; SQLite is just a fast queryable index. The store interface is a clean seam
to swap in Postgres at scale (see DESIGN scaling notes).

## 5. Behavioral staff classification over face identification

**Decision:** Tag a visit as staff from behavior — long dwell, multiple zones,
cash-counter anchoring (≥2 of 3 signals).
**Alternatives considered:** Face recognition of a staff roster, uniform detection,
manual track labeling.
**Trade-off:** False positives on slow lingering shoppers; false negatives on a
roaming clerk. Thresholds are heuristic, not learned.
**Why this for now:** No PII, no labeled training data, and re-runnable without
re-detecting (it's a post-pass over events). The thresholds are CLI-configurable so
the same code scales to full-day footage. **Clip adaptation (important):** the
plan's literal thresholds (dwell >30 min, ≥3 zones, ≥2 cash passes) cannot fire on
2-minute clips, so the "long dwell" signal is clip-relative — `dwell > 40 s` **or**
`> 4× the per-camera median dwell`. On the sample footage this correctly surfaces 3
staff (2 billing operators, 1 floor salesperson); with `--dwell-floor-s 1800
--zones-min 3` it reproduces the plan's full-day behavior exactly.

## 6. POS ↔ CV time-bucket join over identity matching

**Decision:** Attribute POS bills to CV footfall by shared 5-minute time bucket;
conversion = bills ÷ visits per bucket, visit-weighted, capped at 1.0.
**Alternatives considered:** Loyalty-ID matching, per-till camera identity, manual
basket association.
**Trade-off:** Coarse — a busy bucket can mis-attribute which party paid; bills in a
bucket with zero detected footfall are counted but flagged un-attributable.
**Why this for now:** The POS export has no camera/track id and the CV pipeline has
no customer identity (by design), so **time is the only shared axis** (1 bill ≈ 1
paying party). It's the same honest mechanism used to fuse cameras. The conversion
cap and the `bills_without_footfall` evidence field make the approximation explicit
rather than hidden.

## 7. JSONL event log over a message queue

**Decision:** Newline-delimited JSON file as the event transport between worker and
API.
**Alternatives considered:** Kafka, Redis Streams, a relational events table.
**Trade-off:** No real-time streaming, no consumer groups, linear scan to rebuild.
**Why this for now:** Zero infrastructure, diffable, replayable, and trivially
committed as a cold-start `events.sample.jsonl`. A queue is the right answer at N
workers / many cameras (see scaling notes) but is pure overhead for a single
offline ingest.

## 8. Offline ingest + online serve split (the core architecture decision)

**Decision:** Detection/event-derivation runs as a separate `make ingest` step; the
API only ever reads the pre-computed event log.
**Alternatives considered:** Detect on API startup, detect on first request,
stream-process live.
**Trade-off:** The API's data is only as fresh as the last ingest; there's a manual
step to process new video.
**Why this for now:** The 680 MB of footage cannot be processed inside the 2-minute
`docker compose up` acceptance window. Splitting ingest out keeps startup instant
and the API responsive, and lets the heavy CV run on a laptop/overnight. The
`/replay` design (re-ingest a subset on demand) preserves dynamic computation.

## 9. Polling dashboard over WebSockets / SSE

**Decision:** Next.js client components poll the API every 5 s with `useEffect` +
`setInterval`, `cache: 'no-store'`.
**Alternatives considered:** WebSockets, Server-Sent Events, React Query.
**Trade-off:** Up to 5 s stale; N clients re-fetch every endpoint repeatedly.
**Why this for now:** Trivial to reason about, no server-push infrastructure, and
the data updates at human-meaningful cadence (this is analytics, not a trading
desk). SSE is the documented next step at many concurrent clients.

## 10. Pydantic discriminated union over loose dict events

**Decision:** Every event is a typed Pydantic v2 model; the top-level `Event` is a
`type`-discriminated union, validated on the way into the store.
**Alternatives considered:** Plain dicts, dataclasses, JSON Schema validation,
Protobuf/Avro.
**Trade-off:** More upfront model code; schema changes touch the model file.
**Why this for now:** One source of truth for the schema (worker emits, API
validates), free OpenAPI docs, and malformed lines are caught and skipped at load
rather than blowing up a route. Adding a new event type is a new model in the union,
no route changes.

---

## Deliberate deviations from the original plan (honest log)

The plan assumed a single camera feed and full-day footage. Reality differed; these
are the documented departures and why each is correct:

- **Multi-camera by role, not single feed.** The brief gives 5 fixed cameras with
  distinct coverage. We assign each the funnel stage it can observe (CAM 3 footfall,
  CAM 1/2 browse, CAM 5 cash) and fuse by time bucket. Using one camera would have
  produced a weaker, less faithful funnel.
- **`./events` bind mount instead of a named volume.** The api build context is
  `./api`, so its Dockerfile cannot COPY the repo-root `events.sample.jsonl`; an
  empty named volume would leave the API with zero events on a fresh
  `docker compose up` and fail the acceptance gate. The bind mount makes the
  committed sample visible immediately.
- **`billed` funnel stage is never clamped to CV footfall.** The funnel clamps its 4
  CV stages monotonically, but `billed` is POS-sourced; clamping it to a short CV
  sample's footfall would silently hide real revenue (and contradict `/metrics`).
- **`anomalies_current` is a Gauge, not a `_total` Counter.** Detection is a pure,
  query-driven function of a static dataset, so the metric is computed once at
  startup. A counter incremented per `/anomaly` call would just measure dashboard
  poll frequency. (`_total` is also a Prometheus-reserved counter suffix.)
- **POS join uses the stdlib `csv` module, not pandas.** Only 24 bills; dropping
  pandas keeps the API image small enough for the Render free tier.
- **Tests run in two scopes.** `worker/` uses a flat `schemas.py` while `api/` uses a
  `schemas/` package — they cannot share `sys.path`, so worker-geometry tests and
  API tests run as separate pytest invocations, each with its own ≥70% coverage gate.

---

## Out of scope (explicitly not built)

1. **Multi-camera identity fusion (re-ID)** — we fuse by time, not by tracking a
   person across cameras. Naming it is a deliberate trade-off, not an oversight.
2. **Audio / shelf-interaction analytics** — single visual modality only.
3. **Customer demographics (age/gender)** — out of scope and ethically fraught; no
   biometric data is stored.
