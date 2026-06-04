"""
Best-effort demographic estimation (gender / age bucket) for ENTRY events.

IMPORTANT HONESTY NOTE
----------------------
The challenge footage has FULL-FACE BLUR applied to every frame (PDF §3.2), so
true face-based age/gender models cannot work here. This is therefore an
explicitly *best-effort, body-cue* estimate, shipped with a caveat and an
``is_face_hidden=True`` flag on every output. It exists because the provided
``sample_events.jsonl`` carries ``gender_pred``/``age_pred`` and the project owner
opted to surface demographic segments — NOT because it is reliable. Treat the
numbers as low-confidence aggregates, never as facts about an individual. The
API stores no identity; these fields are aggregated and discarded per session.

Backends (env ``DEMOGRAPHICS_BACKEND``)
---------------------------------------
* ``none`` (default) — returns unknowns. Honest no-op; the pipeline emits no
  demographic guesses unless a backend is deliberately enabled.
* ``vlm`` — prompts a vision-language model (Anthropic, if ``ANTHROPIC_API_KEY``
  is set) on the person crop. The prompt is below so the approach is auditable
  (Part D). The model is asked to reason from body/clothing/build since the face
  is blurred, and to return ``unknown`` when unsure rather than guess.

Wiring: an enrichment pass attaches ``estimate()`` output to each visitor's ENTRY
metadata before canonical emission. Off by default so the committed seed stays
demographic-free and honest.
"""

from __future__ import annotations

import os
from typing import Optional

AGE_BUCKETS = ("0-17", "18-24", "25-34", "35-44", "45-54", "55+")

# The exact VLM prompt (documented for Part D / DESIGN.md).
VLM_PROMPT = (
    "This is a low-resolution retail CCTV crop of one person. The FACE IS BLURRED "
    "for privacy, so judge only from body build, posture, hair, and clothing. "
    "Return STRICT JSON: {\"gender_pred\": \"M\"|\"F\"|\"unknown\", "
    "\"age_bucket\": one of [0-17,18-24,25-34,35-44,45-54,55+] or \"unknown\", "
    "\"confidence\": 0.0-1.0}. Prefer \"unknown\" over a low-confidence guess. "
    "Do not attempt to identify the individual."
)


def _bucket_for_age(age: Optional[int]) -> Optional[str]:
    if age is None:
        return None
    for lo, hi, label in [(0, 17, "0-17"), (18, 24, "18-24"), (25, 34, "25-34"),
                          (35, 44, "35-44"), (45, 54, "45-54"), (55, 200, "55+")]:
        if lo <= age <= hi:
            return label
    return None


def _unknown() -> dict:
    return {"gender_pred": None, "age_pred": None, "age_bucket": None, "is_face_hidden": True}


def estimate(image_bgr) -> dict:
    """
    Return {gender_pred, age_pred, age_bucket, is_face_hidden} for a person crop.
    Always sets is_face_hidden=True (footage is face-blurred). Defaults to all
    unknowns unless a backend is configured.
    """
    backend = os.environ.get("DEMOGRAPHICS_BACKEND", "none").lower()
    if backend == "vlm":
        return _estimate_vlm(image_bgr)
    return _unknown()


def _estimate_vlm(image_bgr) -> dict:
    """Prompt a VLM on the crop. Returns unknowns if no key / any error."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _unknown()
    try:  # pragma: no cover - network/model path, not exercised in CI
        import base64
        import json

        import cv2  # noqa: F401
        from anthropic import Anthropic

        ok, buf = cv2.imencode(".jpg", image_bgr)
        if not ok:
            return _unknown()
        b64 = base64.b64encode(buf.tobytes()).decode()
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": VLM_PROMPT},
            ]}],
        )
        data = json.loads(msg.content[0].text)
        g = data.get("gender_pred")
        bucket = data.get("age_bucket")
        return {
            "gender_pred": g if g in ("M", "F") else None,
            "age_pred": None,  # we ask for a bucket, not a point age
            "age_bucket": bucket if bucket in AGE_BUCKETS else None,
            "is_face_hidden": True,
        }
    except Exception:  # noqa: BLE001 - any failure → honest unknown
        return _unknown()
