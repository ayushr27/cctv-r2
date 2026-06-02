# Store Intelligence System — Purplle (Brigade Bangalore)

Turns **5 fixed CCTV feeds + a POS sales export** into store intelligence:
footfall, zone engagement, a session-based conversion funnel, behavioral staff
filtering, and meaningful anomaly detection — served over a FastAPI backend and a
live Next.js dashboard. Ingest is offline (CPU YOLOv8n + BoT-SORT); serving is
online and every endpoint computes live from a queryable event store, so outputs
vary with the query window.

---

## Live demo

> _Placeholders — filled in after the optional Phase 11 deploy._
>
> - **Dashboard (Vercel):** `https://<project>.vercel.app`
> - **API (Render):** `https://<service>.onrender.com`
>
> ⚠️ Render's free tier sleeps after 15 min idle — the first request takes ~45 s to
> wake up. **For evaluation, please use `docker compose up`** (below); the hosted
> demo is supplementary.

---

## Quickstart — three commands

```bash
git clone <repo-url> && cd cctv-r2
docker compose up -d                      # api :8000, dashboard :3000
curl 'http://localhost:8000/metrics'      # real data from the committed sample
```

`/metrics` returns within seconds — the API loads a committed
`events/events.sample.jsonl` (202 real events from the CCTV clips) on startup, so
**no ingest step is needed for a fresh clone**. Open the dashboard at
<http://localhost:3000>.

**Prove outputs vary with input** (the integrity check — different windows, different numbers):

```bash
curl 'http://localhost:8000/metrics?from=2026-04-10T12:00&to=2026-04-10T14:00'
curl 'http://localhost:8000/metrics?from=2026-04-10T19:00&to=2026-04-10T21:00'
```

---

## Endpoints

Every endpoint accepts `from` / `to` ISO-8601 query params (default: full
event+POS range).

| Endpoint | What it returns |
| :------- | :-------------- |
| `GET /health` | status, version, uptime, events_loaded |
| `GET /metrics?from=&to=` | footfall, unique_groups, peak_hour, avg_dwell, conversion, avg_bill_value, total_revenue |
| `GET /funnel?from=&to=&granularity=hour\|day` | 5 funnel stages + drop-off rates + per-hour breakdown |
| `GET /zones?from=&to=` | per-zone visits, dwell stats, conversion proxy |
| `GET /anomaly?since=&kinds=` | detected anomalies (footfall drop, conversion drop, zone starvation) with evidence |
| `GET /investigation?since=&kinds=` | loss-prevention review prompts (unbilled cash approach, long dwell) — camera + timestamp + clip reference, **no identity data** |
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

Four pages, 5-second polling (dark mode):

- **Live** — footfall / conversion / avg-bill / revenue + store-employees / groups /
  peak-hour / avg-dwell KPI cards, and a recent-events feed.
- **Funnel** — Recharts conversion funnel + a zone heatmap over the real store
  floor plan, with per-zone brand revenue (zone footfall joined to POS sales).
- **Anomalies** — severity-colored timeline with expandable evidence.
- **Investigation** — loss-prevention review prompts (camera + timestamp + clip
  reference). Privacy-preserving: behavioural flags only, no identity stored. Pull
  the secured footage for a flag with `make clip CAM=cam5 AT=<sec> PAD=15`.

_Screenshots:_ `docs/live.png` · `docs/funnel.png` · `docs/anomalies.png` _(add before submission)._

---

## Full ingestion path (process your own video)

Ingest is offline and **multi-camera by role** — each camera is assigned the funnel
stage it can observe (CAM 3 = footfall, CAM 1/2 = browse, CAM 5 = cash). Source
clips are H.265 and live outside the mounted `data/` dir, so transcode them in
first:

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
(`schemas/` package) can't share a `sys.path` — see CHOICES.md. 43 tests total;
worker ≥78%, api services ≥89% coverage. CI (`.github/workflows/ci.yml`) runs both
on push and PR.

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
