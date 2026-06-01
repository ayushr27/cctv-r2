"""Unit tests for worker.events.cross_line (oriented line-crossing)."""

import os
import sys

# worker-scoped: put worker/ first so bare `from schemas import` / `from config
# import` inside events.py resolve to the worker modules (see conftest note).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from events import cross_line  # noqa: E402

# A vertical line at x=100 spanning y=0..200. "in" = crossing while x decreases
# (moving right -> left), matching the cam3 entrance orientation.
LINE_X = {"points": [[100, 0], [100, 200]], "direction": "in_when_x_decreases"}
# A horizontal line at y=100 spanning x=0..200. "in" = y decreases (moving up).
LINE_Y = {"points": [[0, 100], [200, 100]], "direction": "in_when_y_decreases"}


def test_crosses_in_direction():
    # right -> left across x=100 => x decreases => IN
    assert cross_line((120, 100), (80, 100), LINE_X) is True
    # below -> above across y=100 => y decreases => IN
    assert cross_line((50, 120), (50, 80), LINE_Y) is True


def test_crosses_out_direction():
    # left -> right across x=100 => x increases => NOT the "in" direction
    assert cross_line((80, 100), (120, 100), LINE_X) is False
    # above -> below across y=100 => y increases => not IN
    assert cross_line((50, 80), (50, 120), LINE_Y) is False


def test_no_cross_when_parallel():
    # movement parallel to the vertical line (same side, only y changes)
    assert cross_line((120, 10), (120, 190), LINE_X) is False
    # stays entirely left of the line
    assert cross_line((50, 10), (60, 190), LINE_X) is False


def test_no_cross_when_segment_misses_line():
    # crosses the x=100 plane but OUTSIDE the segment's y-extent (y>200)
    assert cross_line((120, 300), (80, 300), LINE_X) is False


def test_no_cross_when_touching_endpoint():
    # path ends exactly on the line endpoint (no proper crossing)
    assert cross_line((120, 0), (100, 0), LINE_X) is False
