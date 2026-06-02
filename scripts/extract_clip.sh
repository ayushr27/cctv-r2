#!/usr/bin/env bash
# Extract a short review clip from the SECURED source footage on demand.
#
# Privacy note: clips are NOT pre-generated or committed — an authorised operator
# runs this against the original footage using the camera + in-video timestamp
# from an /investigation incident's clip_ref. Output stays out of the repo.
#
# Usage:
#   scripts/extract_clip.sh <camera> <in_video_seconds> [pad_seconds] [out_path]
# Example (review CAM 5 around 0:24 into the clip, ±15s):
#   scripts/extract_clip.sh cam5 24 15 /tmp/review_cam5.mp4
#
# Map an incident's wall-clock ts to in-video seconds with the camera's ingest
# start-time (cam1=20:10:27, cam2=20:10:02, cam3=20:10:00, cam5=20:09:48):
#   in_video_seconds = (incident_ts - camera_start_time) in seconds
set -euo pipefail

CAM="${1:?camera required (e.g. cam5)}"
AT="${2:?in-video seconds required (e.g. 24)}"
PAD="${3:-15}"
OUT="${4:-/tmp/review_${CAM}_${AT}s.mp4}"
SRC="data/samples/${CAM}.mp4"

[ -f "$SRC" ] || { echo "source not found: $SRC" >&2; exit 1; }

START=$(awk "BEGIN{s=$AT-$PAD; print (s<0)?0:s}")
DUR=$(awk "BEGIN{print 2*$PAD}")

ffmpeg -y -ss "$START" -i "$SRC" -t "$DUR" -c:v libx264 -an "$OUT" >/dev/null 2>&1
echo "wrote $OUT  (${CAM}, ${START}s + ${DUR}s)"
