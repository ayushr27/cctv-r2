from datetime import datetime, timezone, timedelta

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))

# Date of the CCTV footage (matches the POS CSV)
FOOTAGE_DATE = "2026-04-10"

# Default store opening time used to anchor video timestamps to wall-clock time
START_TIME_DEFAULT = "10:00:00"

# Build a timezone-aware datetime for the start of the footage
def get_start_datetime(time_str: str = START_TIME_DEFAULT) -> datetime:
    return datetime.fromisoformat(f"{FOOTAGE_DATE}T{time_str}+05:30")

# YOLOv8 model name — n (nano) for CPU speed
YOLO_MODEL = "yolov8n.pt"

# Only detect persons (class 0 in COCO)
PERSON_CLASS = 0

# Default ingestion frame rate
DEFAULT_FPS = 5
