"""Unit tests for worker.events.point_in_zone + zones.json loading."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from events import point_in_zone  # noqa: E402

SQUARE = [[0, 0], [100, 0], [100, 100], [0, 100]]
ZONES_JSON = os.path.join(os.path.dirname(__file__), "..", "worker", "zones.json")


def test_point_in_polygon_inside():
    assert point_in_zone((50, 50), SQUARE) is True
    assert point_in_zone((1, 1), SQUARE) is True


def test_point_on_boundary():
    # boundary-inclusive (a person standing on the edge still counts)
    assert point_in_zone((0, 50), SQUARE) is True
    assert point_in_zone((100, 100), SQUARE) is True


def test_point_outside():
    assert point_in_zone((150, 50), SQUARE) is False
    assert point_in_zone((-1, -1), SQUARE) is False
    assert point_in_zone((50, 200), SQUARE) is False


def test_zone_load_from_json():
    with open(ZONES_JSON) as f:
        zones = json.load(f)
    # camera-keyed structure
    assert "cam3" in zones and "cam5" in zones
    # cam3 owns the entrance line
    assert zones["cam3"]["entry_line"]["type"] == "line"
    assert len(zones["cam3"]["entry_line"]["points"]) == 2
    # cam5 owns the cash counter polygon
    assert zones["cam5"]["cash_counter"]["type"] == "polygon"
    assert len(zones["cam5"]["cash_counter"]["points"]) >= 3


def test_loaded_polygon_is_usable():
    # a real polygon from zones.json works with point_in_zone
    with open(ZONES_JSON) as f:
        zones = json.load(f)
    poly = zones["cam5"]["cash_counter"]["points"]
    # centroid of the polygon should be inside it
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    assert point_in_zone((cx, cy), poly) is True
