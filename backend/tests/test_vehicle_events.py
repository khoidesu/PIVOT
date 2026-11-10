"""Đầu vào event-driven (DRAFT mục 1, 4.1): vị trí/khả dụng của xe đến qua sự kiện idempotent, làm 'tuổi dữ liệu' có nghĩa thật."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from tests.conftest import auth
from tests.helpers import match, run_worker

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def vid(client, plate):
    return next(v["id"] for v in client.get("/v1/vehicles", headers=auth("carrier_b")).json() if v["plate"] == plate)


def vevent(client, user, vehicle_id, etype, payload=None, at=None, sid=None, entity_type="vehicle"):
    return client.post("/v1/events", headers=auth(user), json={
        "entity_type": entity_type, "entity_id": vehicle_id, "event_type": etype, "payload": payload or {},
        "occurred_at": (at or NOW()).isoformat(), "source_system": "gps-feed", "source_event_id": sid or str(uuid.uuid4())})


def position_age(vehicle_id):
    with SessionLocal() as s:
        return s.get(m.Vehicle, uuid.UUID(vehicle_id)).position_updated_at


def test_position_event_refreshes_a_stale_vehicle(client):
    v = vid(client, "51C-100.08")                      # seed: vị trí 22 phút → DATA_STALE
    before = match(client, "dispatch", "LOT-A-001")
    assert any(r["plate"] == "51C-100.08" and any(x["reason_code"] == "DATA_STALE" for x in r["reasons"]) for r in before["rejections"])
    r = vevent(client, "carrier_b", v, "VEHICLE_POSITION")
    assert r.status_code == 202
    run_worker(client)
    assert (NOW() - position_age(v)).total_seconds() < 30
    after = match(client, "dispatch", "LOT-A-001")
    assert "51C-100.08" in {p["vehicle"]["plate"] for p in after["proposals"]} or \
        not any(r["plate"] == "51C-100.08" and any(x["reason_code"] == "DATA_STALE" for x in r["reasons"]) for r in after["rejections"])


def test_position_events_are_idempotent_and_late_ones_never_move_data_back(client):
    v = vid(client, "51C-100.01")
    newer = NOW() - timedelta(seconds=10)
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", at=newer, sid="gps-1").status_code == 202
    assert [vevent(client, "carrier_b", v, "VEHICLE_POSITION", at=newer, sid="gps-1").status_code for _ in range(5)] == [200] * 5
    run_worker(client)
    applied = position_age(v)
    old = vevent(client, "carrier_b", v, "VEHICLE_POSITION", at=NOW() - timedelta(minutes=30), sid="gps-old")
    run_worker(client)
    assert position_age(v) == applied                                       # tin cũ không kéo lùi
    with SessionLocal() as s:
        assert s.get(m.Event, uuid.UUID(old.json()["event_id"])).quality_status == "late"
        assert s.execute(select(m.Event).where(m.Event.source_event_id == "gps-1")).scalars().all().__len__() == 1


def test_position_event_can_move_the_vehicle_to_a_new_location(client):
    v = vid(client, "51C-100.03")
    kcn2 = next(l["id"] for l in client.get("/v1/locations", headers=auth("carrier_b")).json() if l["name"].startswith("KCN VSIP"))
    vevent(client, "carrier_b", v, "VEHICLE_POSITION", {"location_id": kcn2}); run_worker(client)
    with SessionLocal() as s:
        w = s.execute(select(m.AvailabilityWindow).where(m.AvailabilityWindow.vehicle_id == uuid.UUID(v))).scalars().one()
        assert str(w.location_id) == kcn2


def test_availability_event_updates_the_window_and_changes_the_decision(client):
    v = vid(client, "51C-100.09")                      # seed: rảnh quá muộn → PICKUP_WINDOW_MISSED với LOT-A-006
    run = match(client, "dispatch", "LOT-A-006")
    assert any(r["plate"] == "51C-100.09" and any(x["reason_code"] == "PICKUP_WINDOW_MISSED" for x in r["reasons"]) for r in run["rejections"])
    loc = next(l["id"] for l in client.get("/v1/locations", headers=auth("carrier_b")).json() if l["name"].startswith("KCN Sóng"))
    r = vevent(client, "carrier_b", v, "VEHICLE_AVAILABLE", {"location_id": loc, "free_from": NOW().isoformat(), "free_to": (NOW() + timedelta(hours=8)).isoformat()})
    assert r.status_code == 202
    run_worker(client)
    again = match(client, "dispatch", "LOT-A-006")
    assert not any(r["plate"] == "51C-100.09" and any(x["reason_code"] == "PICKUP_WINDOW_MISSED" for x in r["reasons"]) for r in again["rejections"])
    # tin khả dụng cũ hơn tin đã áp dụng → late, không ghi đè
    old = vevent(client, "carrier_b", v, "VEHICLE_AVAILABLE", {"location_id": loc, "free_from": (NOW() + timedelta(hours=9)).isoformat(), "free_to": (NOW() + timedelta(hours=12)).isoformat()}, at=NOW() - timedelta(minutes=20))
    run_worker(client)
    with SessionLocal() as s:
        assert s.get(m.Event, uuid.UUID(old.json()["event_id"])).quality_status == "late"


def test_only_the_owning_carrier_can_report_for_a_vehicle(client):
    v = vid(client, "51C-100.01")
    for user in ("shipper_a", "node_c", "dispatch"):
        assert vevent(client, user, v, "VEHICLE_POSITION").status_code == 404   # không phải chủ xe → không biết xe có tồn tại
    assert vevent(client, "carrier_b", str(uuid.uuid4()), "VEHICLE_POSITION").status_code == 404


def test_vehicle_event_validation(client):
    v = vid(client, "51C-100.01")
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", {"location_id": str(uuid.uuid4())}).status_code == 422
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", {"location_id": "not-a-uuid"}).status_code == 422
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", at=NOW() + timedelta(hours=2)).status_code == 422        # từ tương lai
    assert vevent(client, "carrier_b", v, "VEHICLE_AVAILABLE", {}).status_code == 422                                    # thiếu location_id
    loc = client.get("/v1/locations", headers=auth("carrier_b")).json()[0]["id"]
    assert vevent(client, "carrier_b", v, "VEHICLE_AVAILABLE", {"location_id": loc, "free_from": NOW().isoformat(), "free_to": (NOW() - timedelta(hours=1)).isoformat()}).status_code == 422
    assert vevent(client, "carrier_b", v, "TRIP_STARTED").status_code == 422             # sai loại thực thể
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]["id"]
    assert vevent(client, "carrier_b", prop, "VEHICLE_POSITION", entity_type="proposal").status_code == 422
