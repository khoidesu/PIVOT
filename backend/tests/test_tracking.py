"""Tracking & Tracing: vị trí qua sự kiện idempotent, mốc geofence đúng thứ tự và một lần, bộ giả lập xác định, phân quyền."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app import models as m
from app.db import SessionLocal
from app.sim import gps
from tests.conftest import auth
from tests.helpers import confirm_all, match, run_worker
from tests.test_vehicle_events import vevent, vid


def confirmed(client):
    p = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    return confirm_all(client, p)


def start_sim(client, prop, user="carrier_b"):
    r = client.post(f"/v1/sim/{prop['id']}/start", headers=auth(user))
    assert r.status_code == 200, r.text
    run_worker(client)  # áp TRIP_STARTED → executing


def tick(prop_id, seconds_after_start, t0):
    with SessionLocal() as s:
        n = gps.tick(s, t0 + timedelta(seconds=seconds_after_start))
        s.commit()
    return n


def sim_start_time(prop_id):
    with SessionLocal() as s:
        return s.get(m.SimTrip, uuid.UUID(prop_id)).updated_at


def milestones(client, user, pid):
    d = client.get(f"/v1/tracking/{pid}", headers=auth(user)).json()
    return [x["code"] for x in d["milestones"] if x["reached"]], d


def test_sim_walks_route_and_milestones_fire_once_in_order(client):
    prop = confirmed(client)
    start_sim(client, prop)
    t0 = sim_start_time(prop["id"])
    for i in range(1, 16):
        assert tick(prop["id"], i * 10, t0) in (0, 1)
        run_worker(client)
    reached, d = milestones(client, "shipper_a", prop["id"])
    assert reached == ["ASSIGNED", "AT_PICKUP", "DEPARTED_PICKUP", "AT_ICD_GATE"]
    assert d["progress_pct"] >= 95 and d["is_simulated"] is True
    assert len(d["track"]) >= 3
    with SessionLocal() as s:
        n = s.execute(select(func.count()).select_from(m.Event).where(
            m.Event.event_type == "MILESTONE_REACHED", m.Event.entity_id == uuid.UUID(prop["id"]))).scalar_one()
    assert n == 3  # mỗi mốc đúng một lần (unique theo chuyến + mốc)


def test_replaying_position_events_does_not_duplicate_track_or_milestones(client):
    prop = confirmed(client)
    start_sim(client, prop)
    t0 = sim_start_time(prop["id"])
    tick(prop["id"], 10, t0)
    run_worker(client)
    with SessionLocal() as s:
        ev = s.execute(select(m.Event).where(m.Event.source_system == "sim-gps", m.Event.event_type == "VEHICLE_POSITION")).scalars().first()
        vehicle_id, payload, at, sid = str(ev.entity_id), ev.payload, ev.occurred_at, ev.source_event_id
    before = client.get(f"/v1/tracking/{prop['id']}", headers=auth("carrier_b")).json()["track"]
    for _ in range(5):  # gửi lặp cùng sự kiện: không tác động thứ hai
        r = client.post("/v1/events", headers=auth("carrier_b"), json={
            "entity_type": "vehicle", "entity_id": vehicle_id, "event_type": "VEHICLE_POSITION", "payload": payload,
            "occurred_at": at.isoformat(), "source_system": "sim-gps", "source_event_id": sid})
        assert r.status_code == 200
    run_worker(client)
    assert client.get(f"/v1/tracking/{prop['id']}", headers=auth("carrier_b")).json()["track"] == before


def test_breakdown_mode_stops_the_vehicle_and_slow_mode_is_slower(client):
    prop = confirmed(client)
    start_sim(client, prop)
    t0 = sim_start_time(prop["id"])
    tick(prop["id"], 10, t0)
    with SessionLocal() as s:
        along_normal = s.get(m.SimTrip, uuid.UUID(prop["id"])).along_km
    assert client.post(f"/v1/sim/{prop['id']}/mode", json={"mode": "breakdown"}, headers=auth("carrier_b")).status_code == 200
    tick(prop["id"], 20, t0)
    with SessionLocal() as s:
        assert s.get(m.SimTrip, uuid.UUID(prop["id"])).along_km == along_normal
    assert client.post(f"/v1/sim/{prop['id']}/mode", json={"mode": "teleport"}, headers=auth("carrier_b")).status_code == 422


def test_tick_is_deterministic(client):
    """Cùng trạng thái + cùng `now` → cùng toạ độ (không dùng ngẫu nhiên)."""
    prop = confirmed(client)
    start_sim(client, prop)
    t0 = sim_start_time(prop["id"])
    tick(prop["id"], 30, t0)
    with SessionLocal() as s:
        a = s.get(m.SimTrip, uuid.UUID(prop["id"])).along_km
        assert abs(a - 45.0 * 30 / 3600 * 20) < 1e-6


def test_tracking_visibility_and_no_commercial_data(client):
    prop = confirmed(client)
    start_sim(client, prop)
    for user in ("shipper_a", "carrier_b", "node_c", "dispatch"):
        rows = client.get("/v1/tracking", headers=auth(user)).json()
        assert [r["proposal_id"] for r in rows] == [prop["id"]], user
        text = client.get(f"/v1/tracking/{prop['id']}", headers=auth(user)).text.lower()
        assert "price" not in text and "customer" not in text
    stranger = client.post("/v1/auth/login", json={"name": "Người lạ", "role": "shipper"}).json()["token"]
    h = auth(stranger)
    assert client.get("/v1/tracking", headers=h).json() == []
    assert client.get(f"/v1/tracking/{prop['id']}", headers=h).status_code == 404
    assert client.post(f"/v1/sim/{prop['id']}/start", headers=h).status_code == 404
    assert client.post(f"/v1/sim/{prop['id']}/start", headers=auth("shipper_a")).status_code == 404  # chủ lô không điều khiển xe


def test_position_payload_validation_and_system_events_blocked(client):
    v = vid(client, "51C-100.01")
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", {"lat": 10.9, "lng": 106.75, "speed_kmh": 40}).status_code == 202
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", {"lat": 10.9}).status_code == 422          # thiếu lng
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", {"lat": 21.0, "lng": 105.8}).status_code == 422  # ngoài hành lang
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", {"lat": 10.9, "lng": 106.7, "speed_kmh": 999}).status_code == 422
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", {"lat": "10.9", "lng": 106.7}).status_code == 422
    prop = confirmed(client)
    r = client.post("/v1/events", headers=auth("carrier_b"), json={
        "entity_id": prop["id"], "event_type": "MILESTONE_REACHED", "payload": {"milestone": "AT_ICD_GATE"},
        "occurred_at": datetime.now(timezone.utc).isoformat(), "source_system": "x", "source_event_id": "fake-ms"})
    assert r.status_code == 422  # không giả mốc từ bên ngoài
