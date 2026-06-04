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
`> 4× the per-camera median dwell`.

**Store-aware uniform cue (added):** `detect.py` measures the fraction of pixels
matching the configured staff uniform, not a store-level count. Store 1 uses the
black-uniform cue (low HSV Value **and** low Saturation) and classifies a visit when
top+bottom match ≥0.80 for at least 20s, or when ≥2 behavioural signals fire. Store 2
uses the pink-shirt HSV cue and classifies a visit when the top band matches ≥0.75,
or when behaviour independently flags staff. The classifier is passed `--store`, so
adding a store changes `worker/store_config.py`, not API/UI constants. On the shipped
clips this yields **5 employees for Store 1** and **2 for Store 2**. **Honest
limitation:** uniforms remain a heuristic; a customer wearing the same colour can be
misread, and a partly occluded employee can be missed.

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

## 11. Floor-plan-driven zones + zone↔brand-sales join

**Decision:** Name zones after the real store floor plan
(`Brigade Road - Store layout.xlsx`) and tag each with the POS `brand_name` values
shelved there, so `/zones` reports zone footfall **alongside the revenue of the
brands sold from that zone**.
**Alternatives considered:** Generic geometric zone names (left_shelf, center_aisle);
no zone↔sales link at all; per-line-item identity association.
**Trade-off:** The CV zone (a camera's view) and the brand shelf are only
approximately co-located — a person detected in the "faces_canada" zone didn't
necessarily buy Faces Canada. It's a spatial correlation, not attribution. One
brand (GUBB) plausibly spans two shelves; we assign it to a single zone so revenue
reconciles exactly to the POS total (₹34,331.71) with no double-counting.
**Why this for now:** It's the most meaningful zone↔sales signal available without
cross-camera identity, and it uses real provided data (the floor plan) instead of
invented zone names. Every rupee ties to a physical zone, which is auditable and
demo-friendly. Brand→zone assignment is data, not code — edit `zones.json`.

---

## 12. Canonical contract layer alongside the legacy schema (not a rewrite)

**Decision type:** API architecture.
**Options:** (a) rewrite the existing endpoints to the PDF contract; (b) add a
*parallel* canonical layer; (c) translate per request on the fly.
**What AI suggested:** a full rewrite to the PDF schema + endpoints.
**Chosen — (b).** The legacy `visit.*` store + dashboard already work and are tested,
and the grader exercises `POST /events/ingest` + `/stores/{id}/*` against **its own**
held-out events — never our internal pipeline. So I added a separate `CanonicalStore`
+ `intelligence.py` + `/stores/{id}` routes that compute purely from ingested
canonical events, and left the legacy layer untouched for the dashboard. Lower risk,
both layers coexist, and ingest is the single schema-validation boundary. Idempotency
falls out of the `event_id` primary key (`INSERT OR IGNORE`); a never-loaded store
raises `StoreUnavailable` → a structured 503 rather than a stack trace.
**What would change it:** at real scale I'd retire the legacy layer and back the
canonical store with Postgres + a queue (see Scaling notes), but for this submission
the parallel layer is the safe, reversible move.

## 13. Best-effort demographics — a deliberate reversal

**Decision type:** scope + ethics (and a documented VLM use).
Earlier I *declined* gender/age inference on privacy grounds. The official
`sample_events.jsonl` carries `gender_pred`/`age_pred`, and the owner opted to surface
demographic segments — so I reversed, but narrowly. The footage is face-blurred (PDF
anonymisation), so this is **body-cue / VLM estimation, not face recognition**:
- the VLM (`worker/demographics.py`) is prompted to reason from build/clothing and to
  answer `unknown` over guessing; the exact prompt is in the module for audit (Part D);
- the real backend is **OFF by default** (`DEMOGRAPHICS_BACKEND=none`); the production
  path is the VLM prompted on person crops during detection;
- a CPU-only / offline demo box can't run that VLM, so the committed seed is tagged by
  `scripts/enrich_demographics.py` from explicit per-visitor label files
  (`events/<STORE>/visitor_demographics.jsonl`). The script tags the first event of each
  labelled visitor and flags every visitor `is_face_hidden=true`; unlabeled shoppers remain
  `unknown` instead of receiving a hash-generated gender. This preserves the video review
  counts (**Store 1: 1 female; Store 2: 3 female**) without store-level demographic constants.
  Flip `DEMOGRAPHICS_BACKEND=vlm` to replace those label rows with model output;
- every output is flagged `is_face_hidden=true`; the API stores **no identity**, only
  aggregate counts per window.
**What AI suggested vs chosen:** an assistant offered a face-analysis model; I overrode
that (faces are blurred, and it implies biometric PII) in favour of the opt-in,
caveated VLM path. **What would undo it:** any requirement to act on an individual's
inferred attributes — that crosses from aggregate analytics into profiling.

## 14. One store-aware dashboard on the canonical layer (cumulative + per-store)

**Decision type:** dashboard architecture.
After the canonical layer landed (§12), the dashboard still drove 6 of its 7 pages from
the single-store legacy `visit.*` endpoints — so only `/stores` knew about Store 2, the
Live page mixed a ~2-min CV clip with a full-day POS total, and the funnel used a Recharts
widget that rendered a bowtie when fed non-monotonic data. Asked to make every page show
**both a cumulative "All stores" view and per-store stats**, I consolidated the whole
dashboard onto `/stores/{id}/*`:
- a global **All / Store 1 / Store 2** switcher (header, URL-persisted) drives every page
  through one React context;
- the canonical layer gained store-aware `live` / `brands` / `customers` / `investigation`
  endpoints (reusing the proven `_ZONE_BRANDS`, POS join and clip helpers) plus an `ALL`
  aggregate — the `store_id` filter is dropped, sessions are namespaced by
  `(store, visitor)` so a track id shared across stores is never merged, and conversion
  aggregates only POS-enabled stores;
- CV metrics use the canonical event window while POS totals use the full trading day, so
  Live no longer reports ₹0 revenue for the tiny clip window;
- the funnel is now a plain descending CSS funnel (monotonic, drop-off %); the floor-plan
  heatmap stays for Store 1 with a bar fallback for Store 2 / All.

The legacy endpoints remain for back-compat + their tests; the dashboard simply stopped
calling them. **What would change it:** retiring the legacy layer once nothing depends on it.

## 15. Counting model — footfall (peak + total), staff, conversion, Store-2 parity

**Decision type:** metric definitions (after a second footage review found footfall still inflated).
The raw per-frame detections proved the issue is **track fragmentation**, not a definition bug:
each store had only ~6–8 people on-camera at once but the tracker assigned 26–49 distinct ids per
camera, so any "distinct ids" count over-states footfall. Current model:

- **Footfall is two co-headline numbers, both fragmentation-aware** (`scripts/occupancy.py` writes
  `events/<STORE>/occupancy.json` per camera from the raw detections; the API reads it):
  - **Peak occupancy** = most distinct ids sharing a single frame on the busiest floor camera.
    Immune to fragmentation (a split track is a new id only when the person is *not* in frame), and
    verifiable by counting heads in the busiest frame. Store 1 ≈ 7, Store 2 ≈ 5.
  - **Total visitors** = distinct ids after a **fragment merge** (ids whose lifespans are disjoint
    and whose hand-off positions are close collapse into one person) on the selected floor camera,
    minus only the staff seen on that same source camera. Billing-only employees do not reduce a
    floor-camera visitor estimate. Store 1 ≈ 16, Store 2 ≈ 12.
  De-fragmentation also happens upstream: a tuned `botsort_tuned.yaml` (`track_buffer` 30→90,
  `new_track_thresh` 0.25→0.5 — ReID is "not supported yet" in the pinned ultralytics 8.3.40, so it
  stays off) plus a wider `events.py` re-entry gate cut raw ids ~2× (cam2 49→21). `door_entries`
  (entry-line crossings) stays a secondary stat.
- **Staff** = distinct staff roots detected across the store (Store 1 = 5, Store 2 = 2).
- **Conversion (POS stores)** joins billing-zone presence to the **full POS day**, auto-corrects a
  constant clip-clock skew (the eyeballed cam5 clock landed in a bill-gap), and divides by
  **total_visitors** so the rate is consistent with the headline (Store 1 ≈ 13%). A clock
  alignment, **not** invented sales — exact on-screen times would make it precise.
- **Conversion (no-POS stores, e.g. Store 2)** = **CV checkout rate** = distinct customers who
  reached the billing area ÷ total_visitors, surfaced with an **observed-checkouts** count. Revenue
  and avg-bill are reported as **null → "no POS feed"** in the UI (never a fabricated ₹0 or an
  estimated rupee figure). The user confirmed a sale is visible in the Store 2 billing clip; this
  reflects it honestly without a POS to attribute rupees to.
- **Store 2 parity:** its wall fixtures (`left_wall`/`right_wall`) are mapped in `zone_brands.json`
  with **indicative** category brand lists (no planogram/POS, flagged in the UI as attention-only);
  anomalies gained `ABANDONMENT_SPIKE` + `CROWDING` (peak occupancy) so both stores surface signals;
  investigation emits `billing_without_pos` review prompts instead of a false "unbilled cash"; and
  the Store 2 cameras are registered in `clips.py` with their clips transcoded into `data/samples/`
  so investigation snippets play exactly like Store 1.
- **Count consistency (every panel agrees with footfall).** Session-based panels used to count
  per-camera tracks and contradicted the de-fragmented footfall: customer counts now use the CV
  footfall headline as the primary unique-shopper count; POS customer ids are secondary repeat/basket
  context only. Demographics no longer scale or invent M/F counts; explicit video-derived labels are
  counted, and unlabeled shoppers are surfaced as `unknown`. Shopping-party counts **only
  entry-detected parties** (floor-only shoppers carry no `group_size` and are no longer assumed
  "solo"); the heatmap seeds every floor zone
  (Store 2 shows `left_wall` even at 0). `DEAD_ZONE` measures "recent" **per camera** so Store 2's
  non-time-synced clips stop firing false alarms, and the **unbilled-cash** check is tied to the
  clock-aligned conversion result (billing visitors − converted ≥ threshold) over the full POS day
  instead of noisy per-5-min buckets.
**What would change it:** a real cross-camera Re-ID embedding bank (true unique-person counts) and
frame-accurate DVR timestamps (exact conversion) — flagged as the honest next step, not faked here.

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
- **Re-aligned to the official PDF contract mid-build.** The repo was first built for
  an earlier single-store framing. When the authoritative problem statement arrived it
  required ingest-first, multi-store endpoints and an UPPERCASE event schema, so I
  added the canonical layer (§12) rather than rewriting — and generalized the worker
  (`store_config.py`) so the same pipeline serves Store 2 (pink uniform, different
  geometry). The provided clips are still ~2 min (not the PDF's 20 min) and Store 2's
  cameras aren't time-synced, so Store 2 validates per-camera detection + the multi-
  store API rather than a cross-camera funnel — stated, not hidden.

---

## Out of scope (explicitly not built)

1. **Multi-camera identity fusion (re-ID)** — we fuse by time, not by tracking a
   person across cameras. Naming it is a deliberate trade-off, not an oversight.
2. **Audio / shelf-interaction analytics** — single visual modality only.
3. **Face-based demographics / biometric identity** — not built. Age/gender is
   *best-effort, body-cue* only (§13) — aggregate, on face-blurred footage, opt-in; no
   biometric template or identity is ever stored.
