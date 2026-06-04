# Store Intelligence System — Purplle (Brigade Bangalore)

Turns **5 fixed CCTV feeds + a POS sales export** into store intelligence:
footfall, zone engagement, a session-based conversion funnel, behavioral staff
filtering, and meaningful anomaly detection — served over a FastAPI backend and a
live Next.js dashboard. Ingest is offline (CPU YOLOv8n + BoT-SORT); serving is
online and every endpoint computes live from a queryable event store, so outputs
vary with the query window.

---

## Live demo

> - **Dashboard (Vercel):** https://cctv-r2.vercel.app
> - **API (Render):** https://purplle-store-intel-api.onrender.com
>
> Render's free tier sleeps after 15 min idle — the first request takes ~45 s to
> wake up. **For evaluation, please use `docker compose up`** (below); the hosted
> demo is supplementary.
>
> **The hosted build ships NO licensed data.** The challenge footage, store
> layouts, and the real POS export are gitignored and never deployed. The public
> API serves the committed event sample + canonical seed and a **synthetic POS
> fixture** (`tests/fixtures/pos_sample.csv`), so revenue/conversion on the live
> URL are clearly-synthetic demo numbers; the layout heatmap falls back to bars and
> footage clips show their text reference. Run locally (with the licensed inputs on
> disk) for full fidelity.

### Deploy it yourself (Render API + Vercel dashboard, both free)

Configs are committed: [`render.yaml`](render.yaml), [`api/Dockerfile.deploy`](api/Dockerfile.deploy),
[`dashboard/.env.production`](dashboard/.env.production). The image is verified at ~280 MB (no
pandas/torch) and answers every endpoint. CORS already allows `*.vercel.app`.

**API → Render**
1. Push this repo to GitHub (already at `github.com/ayushr27/cctv-r2`).
2. [render.com](https://render.com) → **New → Blueprint** → connect the repo. Render reads
   `render.yaml` and provisions `purplle-store-intel-api` (Docker, free, region `singapore`).
3. Wait ~5 min for the first build; watch the log for `Application startup complete`.
4. Verify: `curl https://purplle-store-intel-api.onrender.com/health` then
   `…/stores/STORE_BLR_002/metrics` (first hit after idle takes ~45 s).

**Dashboard → Vercel**
1. [vercel.com](https://vercel.com) → **New Project** → import the same repo.
2. **Root Directory:** `dashboard/` · Framework: Next.js (auto-detected).
3. **Environment Variable:** `NEXT_PUBLIC_API_URL = https://purplle-store-intel-api.onrender.com`
   (your Render URL from above).
4. **Deploy** → URL is `https://cctv-r2.vercel.app`. First data click may take ~45 s if Render is cold.

> Worker stays local — `ultralytics + torch + opencv` (~1 GB) exceed the free tier; you ingest
> footage on your laptop and the committed seed/sample carry the deployed demo.

---

## Quickstart — three commands

```bash
git clone <repo-url> && cd cctv-r2
docker compose up -d                                       # api :8000, dashboard :3000
curl 'http://localhost:8000/stores/STORE_BLR_002/metrics'  # acceptance-gate endpoint
curl 'http://localhost:8000/health'                        # per-store feed status
```

The API loads a committed canonical seed (`events/canonical.seed.jsonl`, derived from
the real CCTV clips) on startup, so **`/stores/STORE_BLR_002/metrics` returns real data
on a fresh clone — no ingest step required** (acceptance gate #2/#4). Open the dashboard
at <http://localhost:3000>.

**Ingest your own events** (PDF `POST /events/ingest` — batch ≤ 500, idempotent by
`event_id`, partial success on malformed rows, accepts the canonical *or* the
`sample_events.jsonl` shape):

```bash
# a single canonical event (the body is a JSON array, or {"events":[...]}):
curl -X POST localhost:8000/events/ingest -H 'Content-Type: application/json' -d '[{
  "event_id":"e1","store_id":"STORE_BLR_002","camera_id":"cam3","visitor_id":"VIS_1",
  "event_type":"ENTRY","timestamp":"2026-04-10T14:40:00Z","is_staff":false,"confidence":0.9}]'
```

The provided `sample_events.jsonl` is JSONL; wrap its lines in a JSON array (or POST in
batches) and the tolerant normalizer maps its lowercase `entry`/`zone_entered`/
`queue_*` shape onto the canonical schema.

**Prove outputs vary with input** (the integrity check — different windows, different numbers):

```bash
curl 'http://localhost:8000/metrics?from=2026-04-10T12:00&to=2026-04-10T14:00'
curl 'http://localhost:8000/metrics?from=2026-04-10T19:00&to=2026-04-10T21:00'
```

---

## Scoring-contract endpoints (PDF)

These are the endpoints the automated harness checks — **multi-store** and
**ingest-first**: `POST` events, then query any `store_id`.

| Endpoint | What it returns |
| :------- | :-------------- |
| `POST /events/ingest` | Accept a batch (≤ 500) of canonical *or* sample-shaped events. Idempotent by `event_id`; partial success → `{received, accepted, duplicates, rejected[]}`; never 5xx on bad rows. |
| `GET /stores/{id}/metrics?from=&to=` | unique visitors (sessions, staff-excluded, re-entry-deduped), conversion rate, avg dwell/zone, queue depth, abandonment rate, demographics. Zero-traffic safe (200 + zeros, never 404). |
| `GET /stores/{id}/funnel` | Entry → Zone → Billing Queue → Purchase, counts + drop-off %. Session-unit; re-entries not double-counted. |
| `GET /stores/{id}/heatmap` | per-zone visit frequency + avg dwell, normalized 0–100, with a `data_confidence` flag (< 20 sessions). |
| `GET /stores/{id}/anomalies` | `QUEUE_SPIKE` / `CONVERSION_DROP` / `DEAD_ZONE` with severity `INFO/WARN/CRITICAL` + a `suggested_action`. |
| `GET /health` | per-store last-event timestamp + lag, with a `STALE_FEED` warning when a feed lags > 10 min. |

Stores: **`STORE_BLR_002`** (Store 1, Brigade Road; POS-joined) and **`STORE_BLR_009`**
(Store 2, pink-uniform staff, no POS). Any ingested `store_id` is also queryable.

```bash
curl 'http://localhost:8000/stores/STORE_BLR_002/funnel'
curl 'http://localhost:8000/stores/STORE_BLR_002/anomalies'
curl 'http://localhost:8000/stores/STORE_BLR_002/heatmap'
```

## Endpoints (dashboard — also live)

Every endpoint accepts `from` / `to` ISO-8601 query params (default: full
event+POS range).

| Endpoint | What it returns |
| :------- | :-------------- |
| `GET /health` | status, version, uptime, events_loaded |
| `GET /metrics?from=&to=` | footfall, unique_groups, peak_hour, avg_dwell, conversion, avg_bill_value, total_revenue |
| `GET /funnel?from=&to=&granularity=hour\|day` | 5 funnel stages + drop-off rates + per-hour breakdown |
| `GET /zones?from=&to=` | per-zone visits, dwell stats, conversion proxy |
| `GET /brands?from=&to=` | per brand-stand engagement: customer attention (dwell, share) joined to POS revenue / units / top products + efficiency signals |
| `GET /customers?from=&to=` | non-demographic segments: solo vs group (CV), new vs repeat (POS), basket composition. **No gender/age inference** |
| `GET /anomaly?since=&kinds=` | detected anomalies (footfall drop, conversion drop, zone starvation) with evidence |
| `GET /investigation?since=&kinds=` | loss-prevention review prompts (unbilled cash approach, long dwell) — camera + timestamp + playable clip, **no identity data** |
| `GET /clip/{camera}` | streams the camera's CCTV clip (HTTP range) so the dashboard plays footage at a flagged instant. Raw footage — **gate behind auth in production** |
| `GET /events?type=&from=&to=&limit=` | paginated raw event feed (limit ≤ 1000) |
| `GET /internal/metrics` | Prometheus exposition format |
| `GET /docs` | auto-generated OpenAPI / Swagger UI |

```bash
curl 'http://localhost:8000/funnel?from=2026-04-10T10:00&to=2026-04-10T22:00&granularity=hour'
curl 'http://localhost:8000/zones'
curl 'http://localhost:8000/anomaly'
curl 'http://localhost:8000/events?type=visit.entered_zone&limit=5'
open http://localhost:8000/docs
```

---

## Dashboard

Seven pages, 5-second polling (dark mode). A global **All stores / Store 1 / Store 2**
switcher in the header drives every page (URL-persisted): each page shows the cumulative
view *or* per-store stats, all from the canonical `/stores/{id}/*` layer.

- **Live** — two co-headline footfall KPIs (**peak occupancy** = people on the busiest
  camera at once, fragmentation-proof; **total visitors** = de-fragmented shoppers) +
  conversion / avg-bill / revenue (POS full day) + store-employees / avg-dwell / peak-hour /
  queue-depth, a best-effort demographics panel (gender split + age histogram), and a
  recent-events feed. Store 2 (no POS) shows a **CV checkout rate** + observed checkouts and
  marks revenue/avg-bill "no POS feed" (no invented rupees).
- **Stores** — the PDF-contract KPIs per store: peak occupancy + total visitors, conversion,
  abandonment, funnel, heatmap, demographics, anomalies.
- **Funnel** — a descending conversion funnel (Entry → Zone → Billing → Purchase, with
  drop-off %) + a zone heatmap over the real Store 1 floor plan (bar fallback for Store 2 /
  All).
- **Brands** — per brand-stand engagement: customer attention vs. POS sales,
  ₹/visit & ₹/attention-minute efficiency, top products sold, and a
  "browsed-but-not-bought" merchandising signal. Store 2 (no POS) shows attention only.
- **Customers** — non-demographic segments: solo vs group shoppers, new vs
  repeat customers, basket composition.
- **Anomalies** — operational detectors for **both stores** (queue spike, conversion drop,
  abandonment spike, crowding/peak-occupancy, dead zone) with severity + suggested action.
- **Investigation** — loss-prevention review prompts (camera + timestamp + playable clip)
  for **both stores** — clicking a Store 2 log plays its CCTV snippet just like Store 1.
  Privacy-preserving: behavioural flags only, no identity stored. POS stores flag unbilled
  cash approaches; no-POS stores (Store 2) surface billing activity for clip review. Pull the
  secured footage for a flag with `make clip CAM=cam5 AT=<sec> PAD=15`.

_Screenshots:_ `docs/live.png` · `docs/funnel.png` · `docs/anomalies.png` _(add before submission)._

---

## Full ingestion path (process your own video)

Ingest is offline and **multi-camera by role** — each camera is assigned the funnel
stage it can observe. **One command per store** runs the whole pipeline
(transcode → detect → events → staff-classify → canonical → optional ingest):

```bash
# Store 1 (black-uniform staff) and Store 2 (pink-uniform staff):
docker compose run --rm worker bash scripts/run_pipeline.sh STORE_BLR_002 "resources/Store 1"
docker compose run --rm worker bash scripts/run_pipeline.sh STORE_BLR_009 "resources/Store 2" http://api:8000
```

`run_pipeline.sh` writes `events/<store>/canonical.jsonl`; the trailing URL (optional)
POSTs the canonical events to `/events/ingest` in batches of 500, so the dashboard +
`/stores/{id}/*` update live. Camera→role + uniform colour live in
`worker/store_config.py` — adding a store is a config entry. (Store 2's clips aren't
time-synced across cameras, so it's per-camera; see CHOICES.)

The manual per-camera steps (handy for re-calibrating one feed) are below. Source
clips are H.265, so transcode them into the mounted `data/` dir first:

```bash
# 1. Transcode each camera to H.264 into the mounted data dir
ffmpeg -i "CCTV Footage/CAM 3.mp4" -c:v libx264 -crf 23 -an data/samples/cam3.mp4

# 2. Detect per camera (anchor wall-clock time from the on-screen clock)
docker compose run --rm worker python detect.py \
  --video /data/samples/cam3.mp4 --out /events/raw_cam3.jsonl --camera cam3 --start-time 20:10:00

# 3. Derive business events per camera (camera-keyed zones.json)
docker compose run --rm worker python events.py \
  --in /events/raw_cam3.jsonl --out /events/events_cam3.jsonl --camera cam3

# 4. Merge events_cam*.jsonl time-sorted into events.jsonl, then classify staff
make classify        # appends track.staff_classified, refreshes events.jsonl
```

Zones are calibrated per camera in `worker/zones.json`; re-annotate against a real
frame with `scripts/annotate_zones.py`. (`make ingest VIDEO=…` is a single-camera
convenience wrapper around step 2.)

---

## Local development

```bash
make up            # docker compose up -d
make down          # stop
make logs          # follow all logs
make test          # API + business-logic tests (in the api image), 70% gate
make test-worker   # worker geometry/zones/re-entry/staff tests, 70% gate
```

Tests run in **two scopes** because `worker/` (flat `schemas.py`) and `api/`
(`schemas/` package) can't share a `sys.path` — see CHOICES.md. 85 tests total;
worker ≥79%, api services ≥90% coverage (incl. ingest idempotency, partial success,
the 500-batch cap, all-staff exclusion, zero-purchase, and re-entry in the funnel).
Each test file carries a `# PROMPT:` / `# CHANGES MADE:` block (Part D). CI
(`.github/workflows/ci.yml`) runs both scopes on push and PR.

Optional Prometheus monitoring: uncomment the `prometheus` service in
`docker-compose.yml` (scrapes `api:8000/internal/metrics`, UI on :9090).

---

## Documentation

- **[DESIGN.md](DESIGN.md)** — architecture diagram, component table, full event
  schema, data flow, scaling notes.
- **[CHOICES.md](CHOICES.md)** — 10 engineering decisions with alternatives and
  trade-offs, plus the honest log of deviations from the original plan.

---

## Honest data caveat

The provided CCTV clips are short samples (~2–3 min, all ~20:09–20:12 IST) while
the POS CSV spans the full trading day (12:15–21:39). They barely overlap in time,
so footfall counts are small and a default-window conversion rate is near-zero —
**this is correct, not a bug.** The system is built to produce meaningful numbers on
longer footage with no code changes. See DESIGN.md and CHOICES.md.

---

## Acknowledgements

[Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) ·
[FastAPI](https://fastapi.tiangolo.com/) ·
[Recharts](https://recharts.org/) ·
[Next.js](https://nextjs.org/) ·
[Prometheus](https://prometheus.io/)
