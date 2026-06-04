# PROMPT: "Write pytest tests for the new canonical PDF-contract layer: the
#   ingest normalizer (sample-shape -> canonical), POST /events/ingest
#   (idempotency, partial success on a bad row, the 500-event batch cap), and
#   the /stores/{id}/{metrics,funnel,heatmap,anomalies} endpoints. Cover the
#   PDF Part C edge cases explicitly: empty/unknown store (200 + zeros, never
#   404), an all-staff clip (excluded from customer metrics), zero purchases,
#   and re-entry in the funnel (REENTRY must not double-count a visitor). Also
#   assert /health surfaces a per-store STALE_FEED, and that a never-loaded
#   CanonicalStore raises StoreUnavailable (the 503 path)."
# CHANGES MADE: Used per-test synthetic store_ids (TEST_*) so cases stay isolated
#   from the committed STORE_BLR_002 seed. Built a small canonical-event factory
#   instead of fixture files. Added a direct unit test of StoreUnavailable rather
#   than mutating the global store mid-request (which the catch-all 500 handler
#   would mask). Pinned timestamps to UTC 'Z' to exercise the parser.

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from services import ingest_normalize  # noqa: E402
from services.canonical_store import CanonicalStore, StoreUnavailable  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def ev(store, visitor, etype, ts, *, zone=None, staff=False, dwell=0, meta=None, camera="cam_test"):
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store,
        "camera_id": camera,
        "visitor_id": visitor,
        "event_type": etype,
        "timestamp": ts,
        "zone_id": zone,
        "dwell_ms": dwell,
        "is_staff": staff,
        "confidence": 0.9,
        "metadata": meta or {},
    }


# --- ingest normalizer (sample shape -> canonical) -------------------------

def test_normalize_sample_entry():
    raw = {"event_type": "entry", "id_token": "ID_1", "store_code": "store_x",
           "camera_id": "cam1", "event_timestamp": "2026-03-08T18:10:05.120000",
           "is_staff": False, "gender_pred": "F", "age_pred": 28, "group_id": "G1",
           "group_size": 2}
    n = ingest_normalize.normalize_event(raw)
    assert n["event_type"] == "ENTRY"
    assert n["visitor_id"] == "ID_1"
    assert n["store_id"] == "store_x"
    assert n["metadata"]["gender_pred"] == "F"
    assert n["metadata"]["age_pred"] == 28


def test_normalize_queue_completed_maps_to_join_with_depth():
    raw = {"event_type": "queue_completed", "track_id": 7, "store_id": "s",
           "camera_id": "cam6", "queue_join_ts": "2026-03-08T18:13:05",
           "wait_seconds": 8, "queue_position_at_join": 3}
    n = ingest_normalize.normalize_event(raw)
    assert n["event_type"] == "BILLING_QUEUE_JOIN"
    assert n["visitor_id"] == "track_7"
    assert n["metadata"]["queue_depth"] == 3
    assert n["dwell_ms"] == 8000


def test_normalize_missing_id_synthesizes_deterministic_event_id():
    raw = {"event_type": "entry", "id_token": "ID_1", "store_code": "s",
           "camera_id": "c", "event_timestamp": "2026-03-08T18:10:05"}
    a = ingest_normalize.normalize_event(raw)["event_id"]
    b = ingest_normalize.normalize_event(raw)["event_id"]
    assert a == b  # deterministic -> idempotent under re-POST


def test_normalize_unmappable_type_raises():
    with pytest.raises(ValueError):
        ingest_normalize.normalize_event({"event_type": "nonsense", "store_id": "s",
                                          "visitor_id": "v", "timestamp": "2026-01-01T00:00:00"})


# --- POST /events/ingest ---------------------------------------------------

def test_ingest_idempotent(client):
    s = "TEST_IDEMP"
    batch = [ev(s, "v1", "ENTRY", "2026-04-10T14:00:00Z")]
    r1 = client.post("/events/ingest", json=batch).json()
    r2 = client.post("/events/ingest", json=batch).json()
    assert r1["accepted"] == 1 and r1["duplicates"] == 0
    assert r2["accepted"] == 0 and r2["duplicates"] == 1


def test_ingest_partial_success(client):
    s = "TEST_PARTIAL"
    good = ev(s, "v1", "ENTRY", "2026-04-10T14:00:00Z")
    r = client.post("/events/ingest", json=[good, {"garbage": True}])
    assert r.status_code == 200  # never 5xx for bad data
    body = r.json()
    assert body["accepted"] == 1
    assert len(body["rejected"]) == 1 and body["rejected"][0]["index"] == 1


def test_ingest_batch_limit(client):
    s = "TEST_BIG"
    big = [ev(s, f"v{i}", "ENTRY", "2026-04-10T14:00:00Z") for i in range(501)]
    r = client.post("/events/ingest", json=big)
    assert r.status_code == 413
    assert "error" in r.json()


def test_ingest_accepts_object_wrapper(client):
    s = "TEST_WRAP"
    r = client.post("/events/ingest", json={"events": [ev(s, "v1", "ENTRY", "2026-04-10T14:00:00Z")]})
    assert r.json()["accepted"] == 1


# --- /stores/{id}/* edge cases --------------------------------------------

def test_unknown_store_returns_zeros_not_404(client):
    r = client.get("/stores/NEVER_INGESTED/metrics")
    assert r.status_code == 200
    j = r.json()
    assert j["unique_visitors"] == 0 and j["conversion_rate"] == 0.0
    assert j["data_confidence"] == "low"


def test_all_staff_excluded_from_metrics(client):
    s = "TEST_ALLSTAFF"
    client.post("/events/ingest", json=[
        ev(s, "st1", "ENTRY", "2026-04-10T14:00:00Z", staff=True),
        ev(s, "st2", "ENTRY", "2026-04-10T14:01:00Z", staff=True),
    ])
    j = client.get(f"/stores/{s}/metrics").json()
    assert j["unique_visitors"] == 0
    assert j["staff_excluded"] == 2


def test_nopos_store_conversion_is_cv_checkout_rate(client):
    s = "TEST_NOPOS"  # not in store_map -> no POS join -> CV-only checkout rate
    client.post("/events/ingest", json=[
        ev(s, "v1", "ENTRY", "2026-04-10T14:00:00Z"),
        ev(s, "v1", "BILLING_QUEUE_JOIN", "2026-04-10T14:02:00Z", zone="cash_counter"),
    ])
    j = client.get(f"/stores/{s}/metrics").json()
    assert j["unique_visitors"] == 1
    # No POS feed -> conversion is the CV checkout rate (billing visitors / footfall),
    # not zero, and revenue stays unattributed (no rupees invented).
    assert j["conversion_method"] == "cv_checkout_rate"
    assert j["observed_checkouts"] == 1
    assert j["conversion_rate"] > 0.0


def test_reentry_not_double_counted_in_funnel(client):
    s = "TEST_REENTRY"
    client.post("/events/ingest", json=[
        ev(s, "v1", "ENTRY", "2026-04-10T14:00:00Z"),
        ev(s, "v1", "EXIT", "2026-04-10T14:05:00Z"),
        ev(s, "v2", "ENTRY", "2026-04-10T14:10:00Z"),
        ev(s, "v2", "REENTRY", "2026-04-10T14:10:01Z", meta={"reentry_of": "v1"}),
    ])
    m = client.get(f"/stores/{s}/metrics").json()
    f = client.get(f"/stores/{s}/funnel").json()
    assert m["unique_visitors"] == 1  # v2 collapses onto v1
    entry_stage = next(x for x in f["stages"] if x["stage"] == "entry")
    assert entry_stage["count"] == 1


def test_funnel_and_heatmap_shapes(client):
    s = "TEST_FUNNEL"
    client.post("/events/ingest", json=[
        ev(s, "v1", "ENTRY", "2026-04-10T14:00:00Z"),
        ev(s, "v1", "ZONE_ENTER", "2026-04-10T14:01:00Z", zone="skincare"),
        ev(s, "v1", "ZONE_EXIT", "2026-04-10T14:02:00Z", zone="skincare", dwell=60000),
    ])
    f = client.get(f"/stores/{s}/funnel").json()
    assert [x["stage"] for x in f["stages"]] == ["entry", "zone_visit", "billing_queue", "purchase"]
    h = client.get(f"/stores/{s}/heatmap").json()
    assert any(z["zone_id"] == "skincare" for z in h["zones"])
    assert h["data_confidence"] == "low"  # < 20 sessions


def test_anomalies_queue_spike(client):
    s = "TEST_QUEUE"
    client.post("/events/ingest", json=[
        ev(s, f"v{i}", "BILLING_QUEUE_JOIN", "2026-04-10T14:00:00Z",
           zone="cash_counter", meta={"queue_depth": 9})
        for i in range(3)
    ])
    a = client.get(f"/stores/{s}/anomalies").json()
    assert any(x["type"] == "QUEUE_SPIKE" and x["severity"] == "CRITICAL" for x in a["anomalies"])
    assert all("suggested_action" in x for x in a["anomalies"])


# --- /health ---------------------------------------------------------------

def test_health_reports_stale_feed(client):
    # The committed seed is historical footage, so STORE_BLR_002 reads as stale.
    h = client.get("/health").json()
    assert h["status"] == "ok"
    assert "STORE_BLR_002" in h["stores"]
    assert h["stores"]["STORE_BLR_002"]["stale"] is True
    assert h["warning"] == "STALE_FEED"


# --- graceful degradation (503 path) --------------------------------------

def test_unloaded_store_raises_store_unavailable():
    fresh = CanonicalStore()  # never .load()ed
    with pytest.raises(StoreUnavailable):
        fresh.fetch("anything")


# PROMPT (multi-store dashboard): "Add tests for the cumulative ALL view and the
#   new store-aware live/brands/customers/investigation endpoints: ALL must union
#   across stores (and not merge a track id shared between two stores), the rich
#   endpoints must be zero-traffic safe and degrade to attention/CV-only for a
#   store with no POS, and the seeded store's /live must report POS full-day
#   revenue (not the tiny CV window) plus best-effort demographics."
# CHANGES MADE: ALL assertions use >= against the union (the seed + other tests'
#   stores are also in ALL), and isolation cases use fresh TEST_* store ids.


# --- ALL (cumulative) aggregation -----------------------------------------

def test_all_unions_across_stores(client):
    a, b = "TEST_ALL_A", "TEST_ALL_B"
    client.post("/events/ingest", json=[
        ev(a, "a1", "ENTRY", "2026-04-10T14:00:00Z"),
        ev(a, "a2", "ENTRY", "2026-04-10T14:01:00Z"),
        ev(b, "b1", "ENTRY", "2026-04-10T14:02:00Z"),
    ])
    ma = client.get(f"/stores/{a}/metrics").json()
    mb = client.get(f"/stores/{b}/metrics").json()
    mall = client.get("/stores/ALL/metrics").json()
    assert ma["unique_visitors"] == 2 and mb["unique_visitors"] == 1
    # ALL unions every ingested store (incl. the seed) -> at least these three
    assert mall["unique_visitors"] >= 3
    fall = client.get("/stores/ALL/funnel").json()
    assert [x["stage"] for x in fall["stages"]] == ["entry", "zone_visit", "billing_queue", "purchase"]


def test_all_does_not_merge_shared_visitor_id_across_stores(client):
    a, b = "TEST_DUP_A", "TEST_DUP_B"
    client.post("/events/ingest", json=[
        ev(a, "dup", "ENTRY", "2026-04-10T15:00:00Z"),
        ev(b, "dup", "ENTRY", "2026-04-10T15:01:00Z"),
    ])
    # same id in each store, counted once per store; namespacing keeps them apart
    assert client.get(f"/stores/{a}/metrics").json()["unique_visitors"] == 1
    assert client.get(f"/stores/{b}/metrics").json()["unique_visitors"] == 1


# --- new store-aware endpoints (live / brands / customers / investigation) --

def test_live_zero_traffic_safe(client):
    j = client.get("/stores/NEVER_LIVE/live").json()
    for k in ("footfall", "conversion_rate", "total_revenue", "peak_hour",
              "recent_events", "demographics", "queue_depth_max"):
        assert k in j
    assert j["footfall"] == 0 and j["recent_events"] == []


def test_live_seed_store_uses_pos_full_day_revenue(client):
    # Regression for the window-mismatch bug: the canonical clip is ~2 min, but
    # POS revenue must reflect the full trading day, not ₹0 for that tiny window.
    j = client.get("/stores/STORE_BLR_002/live").json()
    assert j["footfall"] > 0
    assert j["total_revenue"] > 0
    assert j["demographics"]["gender"]  # seed enriched with best-effort demographics


def test_brands_no_pos_is_attention_only(client):
    s = "TEST_BRANDS_NOPOS"  # not in store_map -> no POS join
    client.post("/events/ingest", json=[
        ev(s, "v1", "ENTRY", "2026-04-10T14:00:00Z"),
        ev(s, "v1", "ZONE_ENTER", "2026-04-10T14:01:00Z", zone="alps_goodness"),
        ev(s, "v1", "ZONE_EXIT", "2026-04-10T14:02:00Z", zone="alps_goodness", dwell=5000),
    ])
    j = client.get(f"/stores/{s}/brands").json()
    assert j["note"]  # "no POS" note present
    stand = next((x for x in j["stands"] if x["stand"] == "alps_goodness"), None)
    assert stand and stand["revenue"] == 0.0 and stand["attention_seconds"] > 0


def test_customers_group_size_and_no_pos_note(client):
    s = "TEST_CUST_NOPOS"
    client.post("/events/ingest", json=[
        ev(s, "v1", "ENTRY", "2026-04-10T14:00:00Z", meta={"group_size": 3}),
    ])
    j = client.get(f"/stores/{s}/customers").json()
    assert j["basket"]["bills"] == 0
    assert j["shopping_party"]["group"] == 1  # group_size 3 -> a group party
    assert j["note"]


def test_investigation_billing_without_pos(client):
    s = "TEST_INV"  # no POS -> cannot reconcile, surfaced as a billing_without_pos prompt
    client.post("/events/ingest", json=[
        ev(s, f"v{i}", "BILLING_QUEUE_JOIN", "2026-04-10T14:00:30Z", zone="cash_counter")
        for i in range(3)
    ])
    j = client.get(f"/stores/{s}/investigation").json()
    assert j["count"] >= 1
    # No POS feed -> not falsely flagged "unbilled"; surfaced for clip review instead.
    assert any(i["kind"] == "billing_without_pos" for i in j["incidents"])
    assert all("clip_ref" in i for i in j["incidents"])


# --- footfall = in-store occupancy (not per-camera recount) ----------------

def test_footfall_is_in_store_not_per_camera_recount(client):
    # One real door crossing + two floor-only tracks (no entry). Footfall is the
    # in-store (busiest-camera) count; door_entries counts only the crossing.
    s = "TEST_FOOTFALL"
    client.post("/events/ingest", json=[
        ev(s, "v1", "ENTRY", "2026-04-10T14:00:00Z"),
        ev(s, "v2", "ZONE_ENTER", "2026-04-10T14:01:00Z", zone="z"),
        ev(s, "v3", "ZONE_ENTER", "2026-04-10T14:02:00Z", zone="z"),
    ])
    m = client.get(f"/stores/{s}/metrics").json()
    assert m["door_entries"] == 1       # only v1 crossed the door line
    assert m["unique_visitors"] == 3    # in-store = distinct on the camera
    assert m["zone_visitors"] == 2      # floor engagement
    # Two co-headline footfall numbers are always present (peak + total). Without
    # a raw occupancy.json the API falls back to the busiest-camera distinct.
    assert m["total_visitors"] == 3
    assert m["peak_occupancy"] == 3
    assert m["unique_visitors"] == m["total_visitors"]


def test_nopos_live_revenue_is_null_not_zero(client):
    # A store with no POS feed must report revenue/avg-bill as null (the UI shows
    # "no POS feed"), never a misleading ₹0.
    s = "TEST_NOPOS_LIVE"
    client.post("/events/ingest", json=[ev(s, "v1", "ENTRY", "2026-04-10T14:00:00Z")])
    j = client.get(f"/stores/{s}/live").json()
    assert j["has_pos"] is False
    assert j["total_revenue"] is None
    assert j["avg_bill_value"] is None


def test_conversion_reflects_billing_after_clock_align(client):
    # Regression for the user's "I can see billing in the video, why is conversion
    # 0?" — the CV billing clip's eyeballed clock lands in a POS bill-gap, so the
    # join auto-corrects the skew and conversion becomes > 0.
    j = client.get("/stores/STORE_BLR_002/metrics").json()
    assert j["conversion_rate"] > 0
    assert "auto-aligned" in j["conversion_evidence"]


def test_seed_store_employee_and_demographic_targets(client):
    s1 = client.get("/stores/STORE_BLR_002/metrics").json()
    s2 = client.get("/stores/STORE_BLR_009/metrics").json()
    assert s1["staff_excluded"] == 5
    assert s2["staff_excluded"] == 2
    assert s1["total_visitors"] == 16
    assert s2["total_visitors"] == 12
    assert s1["demographics"]["gender"]["F"] == 1
    assert s2["demographics"]["gender"]["F"] == 3


def test_seed_customers_cv_unique_is_primary(client):
    for sid in ("STORE_BLR_002", "STORE_BLR_009"):
        metrics = client.get(f"/stores/{sid}/metrics").json()
        customers = client.get(f"/stores/{sid}/customers").json()
        assert customers["cv_customers"]["unique"] == metrics["total_visitors"]
        assert customers["customers"]["unique"] == metrics["total_visitors"]
    store2 = client.get("/stores/STORE_BLR_009/customers").json()
    assert store2["pos_customers"]["basis"].startswith("unavailable")
    assert store2["basket"]["bills"] == 0
    assert store2["note"]


def test_seed_anomalies_include_incident_summaries(client):
    for sid in ("STORE_BLR_002", "STORE_BLR_009"):
        body = client.get(f"/stores/{sid}/anomalies").json()
        incidents = [a for a in body["anomalies"] if a["type"] == "INCIDENT_REVIEW"]
        assert incidents, sid
        assert all("suggested_action" in a and a["evidence"] for a in incidents)


def test_seed_investigation_has_structured_logs(client):
    for sid in ("STORE_BLR_002", "STORE_BLR_009"):
        body = client.get(f"/stores/{sid}/investigation").json()
        assert body["incidents"], sid
        inc = body["incidents"][0]
        assert {"title", "summary", "recommended_action", "metrics", "supporting_events", "clip_ref"} <= set(inc)
        assert inc["supporting_events"]
        assert {"ts", "camera", "event_type", "zone", "queue_depth"} <= set(inc["supporting_events"][0])


# --- counts consistent with footfall (no per-camera inflation) -------------

def test_demographics_uses_explicit_labels_without_scaling(client):
    # Same 6 people seen on TWO cameras -> 12 labelled sessions. The API should
    # not rescale or invent a different M/F split; explicit labels pass through.
    s = "TEST_DEMO_SCALE"
    evs = []
    for i in range(6):
        g = "F" if i % 2 == 0 else "M"
        for cam in ("ca", "cb"):
            evs.append(ev(s, f"{cam}{i}", "ZONE_ENTER", f"2026-04-10T14:00:0{i}Z",
                          zone="z", meta={"gender_pred": g, "age_bucket": "25-34"}, camera=cam))
    client.post("/events/ingest", json=evs)
    j = client.get(f"/stores/{s}/metrics").json()
    tv = j["total_visitors"]
    assert tv == 6
    assert j["demographics"]["gender"]["F"] == 6
    assert j["demographics"]["gender"]["M"] == 6
    assert "scaled" not in j["demographics"]["note"]


def test_demographics_normalizes_gender_label_variants(client):
    s = "TEST_DEMO_NORMALIZE"
    client.post("/events/ingest", json=[
        ev(s, "v1", "ZONE_ENTER", "2026-04-10T14:00:00Z", meta={"gender_pred": "female"}, camera="c"),
        ev(s, "v2", "ZONE_ENTER", "2026-04-10T14:00:01Z", meta={"gender_pred": "Woman"}, camera="c"),
        ev(s, "v3", "ZONE_ENTER", "2026-04-10T14:00:02Z", meta={"gender_pred": "MALE"}, camera="c"),
        ev(s, "v4", "ZONE_ENTER", "2026-04-10T14:00:03Z", meta={"gender_pred": "unknown"}, camera="c"),
    ])
    j = client.get(f"/stores/{s}/metrics").json()
    assert j["demographics"]["gender"]["F"] == 2
    assert j["demographics"]["gender"]["M"] == 1
    assert j["demographics"]["gender"]["unknown"] == 1


def test_shopping_party_counts_only_entry_detected(client):
    # Floor-only shoppers carry no group_size and must NOT be counted as solo.
    s = "TEST_PARTY"
    client.post("/events/ingest", json=[
        ev(s, "e1", "ENTRY", "2026-04-10T14:00:00Z", meta={"group_size": 1}),
        ev(s, "e2", "ENTRY", "2026-04-10T14:00:05Z", meta={"group_size": 2}),
        ev(s, "f1", "ZONE_ENTER", "2026-04-10T14:01:00Z", zone="z"),  # floor-only, no group
        ev(s, "f2", "ZONE_ENTER", "2026-04-10T14:02:00Z", zone="z"),
    ])
    sp = client.get(f"/stores/{s}/customers").json()["shopping_party"]
    assert sp["entry_detected"] == 2          # only the two ENTRY parties
    assert sp["solo"] + sp["group"] == 2      # floor-only excluded, not counted solo
    assert sp["solo"] == 1 and sp["group"] == 1


def test_dead_zone_uses_per_camera_window(client):
    # Two cameras whose clips sit hours apart (not time-synced): a zone active right
    # up to its own camera's last frame must NOT be flagged dead just because another
    # camera recorded hours later.
    s = "TEST_DEADZONE"
    client.post("/events/ingest", json=[
        ev(s, "v1", "ZONE_ENTER", "2026-04-10T15:00:00Z", zone="early_zone", camera="cam_early"),
        ev(s, "v1", "ZONE_EXIT", "2026-04-10T15:00:30Z", zone="early_zone", camera="cam_early"),
        ev(s, "v2", "ZONE_ENTER", "2026-04-10T19:00:00Z", zone="late_zone", camera="cam_late"),
    ])
    dead = [a for a in client.get(f"/stores/{s}/anomalies").json()["anomalies"]
            if a["type"] == "DEAD_ZONE"]
    assert not any(a.get("zone_id") == "early_zone" for a in dead)


def test_heatmap_sessions_equals_footfall(client):
    s = "TEST_HEATMAP"
    client.post("/events/ingest", json=[
        ev(s, f"v{i}", "ZONE_ENTER", f"2026-04-10T14:00:0{i}Z", zone="z") for i in range(4)
    ])
    h = client.get(f"/stores/{s}/heatmap").json()
    m = client.get(f"/stores/{s}/metrics").json()
    assert h["sessions"] == m["total_visitors"]
