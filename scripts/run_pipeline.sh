#!/usr/bin/env bash
#
# End-to-end detection pipeline for ONE store:
#   clips -> detect (YOLOv8n+BoT-SORT) -> business events -> staff classify
#         -> canonical PDF-schema events -> (optional) POST /events/ingest
#
# Detection needs the worker image (ultralytics/opencv/ffmpeg), so run it there:
#   docker compose run --rm worker bash scripts/run_pipeline.sh STORE_BLR_002 "resources/Store 1"
#   docker compose run --rm worker bash scripts/run_pipeline.sh STORE_BLR_009 "resources/Store 2" http://api:8000
# (The compose file mounts ./scripts, ./resources and ./events into the worker.)
#
# Args:  STORE_ID   FOOTAGE_DIR   [INGEST_BASE_URL]
# Output: <events>/<STORE_ID>/canonical.jsonl  (+ raw_/events_ intermediates)
#
# Camera→clip mapping lives here; camera→role/uniform/start lives in
# worker/store_config.py — keep the two stores in sync across both.
set -euo pipefail
cd "$(dirname "$0")/.."          # repo root (host) or /app (worker image)

# Worker modules sit at the cwd inside the worker image, or under worker/ on a host.
if [ -f detect.py ]; then W="."; else W="worker"; fi
export PYTHONPATH="$W:${PYTHONPATH:-}"
ZONES="zones.json"; [ -f "$W/zones.json" ] && ZONES="$W/zones.json"
OUTROOT="events"; [ -d /events ] && OUTROOT="/events"

STORE="${1:?store_id, e.g. STORE_BLR_002}"
FOOTAGE="${2:?footage dir, e.g. 'resources/Store 1'}"
INGEST="${3:-}"
OUT="${OUTROOT}/${STORE}"
mkdir -p "$OUT"

# clip basename (no .mp4) -> camera id
declare -A CLIPS
case "$STORE" in
  STORE_BLR_002) CLIPS=( ["CAM 3 - entry"]=cam3 ["CAM 1 - zone"]=cam1 ["CAM 2 - zone"]=cam2 ["CAM 5 - billing"]=cam5 ) ;;
  STORE_BLR_009) CLIPS=( ["entry 1"]=entry1 ["entry 2"]=entry2 ["zone"]=zone ["billing_area"]=billing ) ;;
  *) echo "unknown store $STORE (add it to store_config.py + this script)"; exit 1 ;;
esac

events_files=()
for clip in "${!CLIPS[@]}"; do
  cam="${CLIPS[$clip]}"
  src="${FOOTAGE}/${clip}.mp4"
  [ -f "$src" ] || { echo "skip: missing $src"; continue; }
  h264="${OUT}/_transcoded_${cam}.mp4"
  [ -f "$h264" ] || ffmpeg -y -loglevel error -i "$src" -c:v libx264 -crf 23 -an "$h264"
  start="$(python -c "import store_config as s;print(s.camera_start('$STORE','$cam') or '10:00:00')")"
  echo ">> [$cam] detect (start $start, store $STORE)"
  python "$W/detect.py" --video "$h264" --out "$OUT/raw_${cam}.jsonl" \
         --camera "$cam" --store "$STORE" --start-time "$start"
  # Wider re-entry gate + end timeout so a briefly-occluded shopper keeps one
  # visit_id (de-fragmentation, paired with the tuned botsort_tuned.yaml tracker).
  python "$W/events.py" --in "$OUT/raw_${cam}.jsonl" --out "$OUT/events_${cam}.jsonl" \
         --camera "$cam" --zones "$ZONES" \
         --end-timeout-s 15 --reentry-gate-s 15 --reentry-gate-px 180
  events_files+=("$OUT/events_${cam}.jsonl")
done

[ ${#events_files[@]} -gt 0 ] || { echo "no clips processed"; exit 1; }

# Peak-concurrent + de-fragmented visitor counts straight from the raw detections
# -> occupancy.json (the API's footfall headline source). Pure stdlib.
echo ">> occupancy (peak + de-fragmented visitors per camera)"
python scripts/occupancy.py "$OUT"

echo ">> merge + classify staff + convert to canonical"
cat "${events_files[@]}" > "$OUT/events.merged.jsonl"
python "$W/classify.py" --store "$STORE" --in "$OUT/events.merged.jsonl" --out "$OUT/events.jsonl"
python scripts/internal_to_canonical.py "$OUT/events.jsonl" "$OUT/canonical.jsonl" --store-id "$STORE"
# Best-effort demographics on ENTRY events. This is the OFFLINE stand-in for the
# real VLM backend (worker/demographics.py): run that instead by setting
# DEMOGRAPHICS_BACKEND=vlm + ANTHROPIC_API_KEY during detection. See CHOICES.md.
python scripts/enrich_demographics.py "$OUT/canonical.jsonl"
echo ">> canonical events: $(wc -l < "$OUT/canonical.jsonl")  ($OUT/canonical.jsonl)"

if [ -n "$INGEST" ]; then
  echo ">> ingesting to ${INGEST%/}/events/ingest (batches of 500)"
  python - "$OUT/canonical.jsonl" "$INGEST" <<'PY'
import json, sys, urllib.request
path, base = sys.argv[1], sys.argv[2].rstrip("/")
evs = [json.loads(l) for l in open(path) if l.strip()]
for i in range(0, len(evs), 500):
    body = json.dumps(evs[i:i + 500]).encode()
    req = urllib.request.Request(base + "/events/ingest", data=body,
                                 headers={"Content-Type": "application/json"})
    print("  ", urllib.request.urlopen(req).read().decode()[:160])
PY
fi
echo "done: $STORE"
