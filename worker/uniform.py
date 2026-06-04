"""
Staff-uniform colour matching — the per-store generalization of the original
black-only ``outfit_darkness``.

``uniform_fraction(img, bbox, spec)`` returns (top_fraction, bottom_fraction) of
pixels in the torso and leg bands that match the store's uniform, where ``spec``
comes from store_config:

  {"mode": "black"}                              -> low Value AND low Saturation
  {"mode": "hsv", "lo": [...], "hi": [...]}      -> inside an HSV box (e.g. pink)

cv2/numpy are imported lazily so importing this module (e.g. in unit tests that
only exercise the masking maths via injected arrays) doesn't require the full ML
stack. The classifier then thresholds the returned fraction exactly as before —
"fraction of uniform-coloured pixels", whatever the colour.
"""

from __future__ import annotations

from typing import Sequence, Tuple

# Black = dark AND desaturated (separates a black uniform from navy/maroon on
# dim CCTV, where a brightness-only test flags almost everyone).
BLACK_V_MAX = 80
BLACK_S_MAX = 55


def _band_fraction(img, x1, y1, bw, bh, ya, yb, cx1, cx2, spec) -> float:
    import cv2
    import numpy as np

    ry1 = y1 + int(ya * bh)
    ry2 = y1 + int(yb * bh)
    band = img[ry1:ry2, cx1:cx2]
    if band.size == 0:
        return 0.0
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    if spec.get("mode") == "hsv":
        lo, hi = spec["lo"], spec["hi"]
        mask = (
            (h >= lo[0]) & (h <= hi[0])
            & (s >= lo[1]) & (s <= hi[1])
            & (v >= lo[2]) & (v <= hi[2])
        )
    else:  # "black"
        mask = (v < BLACK_V_MAX) & (s < BLACK_S_MAX)
    return round(float(np.mean(mask)), 3)


def uniform_fraction(img, bbox: Sequence[float], spec: dict) -> Tuple[float, float]:
    """
    Fraction of uniform-coloured pixels in the torso (0.15–0.55 of height) and
    legs (0.55–0.92) of a person box, center-cropped horizontally (0.25–0.75) to
    avoid arms/background. Returns (top, bottom) in [0,1]; (0,0) for tiny crops.
    """
    h_img, w_img = img.shape[:2]
    x1, y1, x2, y2 = bbox
    x1 = max(0, int(x1)); y1 = max(0, int(y1))
    x2 = min(w_img, int(x2)); y2 = min(h_img, int(y2))
    bw, bh = x2 - x1, y2 - y1
    if bw < 6 or bh < 12:
        return 0.0, 0.0
    cx1 = x1 + int(0.25 * bw)
    cx2 = x1 + int(0.75 * bw)
    if cx2 <= cx1:
        return 0.0, 0.0
    top = _band_fraction(img, x1, y1, bw, bh, 0.15, 0.55, cx1, cx2, spec)
    bot = _band_fraction(img, x1, y1, bw, bh, 0.55, 0.92, cx1, cx2, spec)
    return top, bot


def outfit_darkness(img, bbox: Sequence[float]) -> Tuple[float, float]:
    """Back-compat wrapper: the original black-uniform special case."""
    return uniform_fraction(img, bbox, {"mode": "black"})
