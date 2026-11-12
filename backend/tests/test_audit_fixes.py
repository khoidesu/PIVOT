"""Hồi quy cho các lỗi tìm thấy khi rà soát toàn bộ mã (12/11/2026):
B1. xe `offline` (vd sau khi hỏng + ghép lại) không bao giờ trở lại `available` dù nhà vận tải báo VEHICLE_AVAILABLE;
B2. `customer_name` > 200 ký tự / `price_vnd` vượt BIGINT làm DB lỗi → HTTP 500 thay vì 422;
B3. lỗi trong khâu dọn nền (sweep) làm cả vòng worker dừng, job outbox không được xử lý;
B4. đăng nhập tạo tên mới nhưng gặp lỗi ràng buộc KHÁC race (vd trùng biển số) → trả khoá của người dùng không tồn tại;
B5. biển số xe sinh cho nhà vận tải mới chỉ có 16^4 khả năng → va chạm khi có vài trăm nhà vận tải."""
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models as m
from app.db import SessionLocal
from tests.conftest import auth
from tests.helpers import confirm_all, match, post_event, run_worker
from tests.test_vehicle_events import NOW, vevent, vid


def _avail(client, user, vehicle_id):
    loc = next(l["id"] for l in client.get("/v1/locations", headers=auth(user)).json() if l["kind"] == "depot")
    return vevent(client, user, vehicle_id, "VEHICLE_AVAILABLE",
                  {"location_id": loc, "free_from": NOW().isoformat(), "free_to": (NOW() + timedelta(hours=8)).isoformat()})


def _status(vehicle_id):
    with SessionLocal() as s:
        return s.get(m.Vehicle, uuid.UUID(vehicle_id)).status


# ---------------------------------------------------------------- B1
def test_offline_vehicle_returns_to_service_when_the_carrier_reports_it_available(client):
    v = vid(client, "51C-100.10")                              # seed: offline
    assert _status(v) == "offline"
    assert _avail(client, "carrier_b", v).status_code == 202
    run_worker(client)
    assert _status(v) == "available"


def test_available_event_never_frees_a_vehicle_that_is_committed_to_a_trip(client):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    veh = next(v for v in client.get("/v1/vehicles", headers=auth("carrier_b")).json() if v["plate"] == prop["vehicle"]["plate"])
    assert _status(veh["id"]) == "committed"
    assert _avail(client, "carrier_b", veh["id"]).status_code == 202
    run_worker(client)
    assert _status(veh["id"]) == "committed"                   # chuyến đang cam kết: không tự trả xe


def test_breakdown_replan_then_available_makes_the_vehicle_matchable_again(client):
    first = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    prop = confirm_all(client, first)
    assert post_event(client, "carrier_b", prop["id"], "TRIP_STARTED").status_code == 202
    run_worker(client)
    veh = next(v for v in client.get("/v1/vehicles", headers=auth("carrier_b")).json() if v["plate"] == prop["vehicle"]["plate"])
    r = client.post(f"/v1/events", headers=auth("carrier_b"), json={
        "entity_id": prop["id"], "event_type": "INCIDENT_REPORTED", "payload": {"kind": "BREAKDOWN"},
        "occurred_at": NOW().isoformat(), "source_system": "carrier-tms", "source_event_id": str(uuid.uuid4())})
    assert r.status_code == 202
    run_worker(client)
    cur = client.get(f"/v1/proposals/{prop['id']}", headers=auth("shipper_a")).json()
    assert client.post(f"/v1/proposals/{prop['id']}/replan", json={"version": cur["version"]}, headers=auth("shipper_a")).status_code == 200
    assert _status(veh["id"]) == "offline"                     # xe hỏng không được đề xuất lại…
    assert _avail(client, "carrier_b", veh["id"]).status_code == 202
    vevent(client, "carrier_b", veh["id"], "VEHICLE_POSITION"); run_worker(client)
    assert _status(veh["id"]) == "available"                   # …cho tới khi nhà vận tải báo khả dụng


# ---------------------------------------------------------------- B2
def _body(**over):
    now = datetime.now(timezone.utc)
    locs = {l["kind"]: l["id"] for l in over.pop("_locs")}
    base = {"code": f"LOT-{uuid.uuid4().hex[:6]}", "cargo_type": "dry", "weight_kg": 1000, "volume_m3": 5,
            "origin_location_id": locs["industrial_zone"], "dest_location_id": locs["icd"],
            "ready_at": (now + timedelta(hours=1)).isoformat(), "pickup_deadline": (now + timedelta(hours=4)).isoformat(),
            "cutoff_at": (now + timedelta(hours=12)).isoformat()}
    return base | over


@pytest.mark.parametrize("field,value", [("customer_name", "x" * 201), ("price_vnd", 10 ** 19), ("code", "x" * 41), ("cargo_type", "y" * 31)])
def test_oversized_inputs_are_rejected_with_422_not_500(client, field, value):
    locs = client.get("/v1/locations", headers=auth("shipper_a")).json()
    r = client.post("/v1/shipments", headers=auth("shipper_a"), json=_body(_locs=locs, **{field: value}))
    assert r.status_code == 422, r.text


def test_oversized_update_is_rejected_with_422_not_500(client):
    sid = next(s for s in client.get("/v1/shipments", headers=auth("shipper_a")).json() if s["code"] == "LOT-A-001")
    for patch in ({"customer_name": "x" * 201}, {"price_vnd": 10 ** 19}):
        r = client.patch(f"/v1/shipments/{sid['id']}", headers=auth("shipper_a"), json={"version": sid["version"], **patch})
        assert r.status_code == 422, r.text


def test_a_normal_long_customer_name_is_still_accepted(client):
    locs = client.get("/v1/locations", headers=auth("shipper_a")).json()
    r = client.post("/v1/shipments", headers=auth("shipper_a"), json=_body(_locs=locs, customer_name="x" * 200, price_vnd=10 ** 12))
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------- B3
def test_a_failing_sweep_does_not_stop_the_outbox_from_being_processed(client, monkeypatch):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    assert post_event(client, "carrier_b", prop["id"], "TRIP_STARTED").status_code == 202

    def boom(*_a, **_k):
        raise RuntimeError("sweep down")
    monkeypatch.setattr("app.incidents.service.sweep", boom)
    stats = run_worker(client)                                  # không được ném lỗi
    assert stats["done"] >= 1 and stats["failed"] == 0
    assert client.get(f"/v1/proposals/{prop['id']}", headers=auth("shipper_a")).json()["status"] == "executing"


def test_background_loop_survives_an_exception(monkeypatch):
    import asyncio
    from app import main

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db hiccup")
        return {}
    monkeypatch.setattr(main, "process_pending", flaky)
    monkeypatch.setattr(main, "sim_tick_once", lambda: None)

    async def go():
        task = asyncio.create_task(main.background_loop(interval=0.01))
        await asyncio.sleep(0.15)
        alive = not task.done()
        task.cancel()
        return alive
    assert asyncio.run(go()) is True and calls["n"] >= 2        # sau lỗi đầu tiên vòng lặp vẫn chạy tiếp


# ---------------------------------------------------------------- B4 / B5
def test_login_does_not_return_a_phantom_account_when_creation_fails_for_another_reason(client, monkeypatch):
    from app import accounts

    def collide(*_a, **_k):
        raise IntegrityError("INSERT", {}, Exception("duplicate key value violates unique constraint vehicles_plate_key"))
    monkeypatch.setattr(accounts, "provision_org", collide)
    with SessionLocal() as s, pytest.raises(IntegrityError):
        accounts.login_or_register(s, "Người Mới Tinh", "carrier")
    with SessionLocal() as s:
        assert s.execute(select(m.User.id).where(m.User.email == "nguoi-moi-tinh-carrier@demo.local")).first() is None


def test_generated_plates_have_enough_entropy_to_avoid_collisions(client):
    r = client.post("/v1/auth/login", json={"name": "Hãng Xe Mới", "role": "carrier"})
    assert r.status_code == 200
    plates = [v["plate"] for v in client.get("/v1/vehicles", headers={"Authorization": f"Bearer dev:{r.json()['token']}"}).json()]
    assert len(plates) == 4 and all(re.fullmatch(r"61[0-9A-F]-[0-9a-f]{6}\.\d\d", p) for p in plates)


# ---------------------------------------------------------------- B6 / B7: phạm vi truy vấn
def _flood_other_tenant_trips(n=120):
    """n chuyến `completed` MỚI HƠN của tổ chức B (xe B + lô B) — không liên quan tới tổ chức A."""
    with SessionLocal() as s:
        veh = s.execute(select(m.Vehicle).where(m.Vehicle.plate == "51C-100.01")).scalars().one()
        ship = s.execute(select(m.Shipment).where(m.Shipment.code == "LOT-B-011")).scalars().one()
        now = datetime.now(timezone.utc)
        for i in range(n):
            s.add(m.Proposal(shipment_id=ship.id, vehicle_id=veh.id, status="completed", rule_version="rules-v1",
                             assumption_version="assume-v2", created_at=now + timedelta(seconds=i + 1)))
        s.commit()


def test_tracking_lists_my_trip_even_when_many_newer_trips_belong_to_others(client):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    with SessionLocal() as s:  # chuyến của A là chuyến CŨ nhất
        s.get(m.Proposal, uuid.UUID(prop["id"])).created_at = datetime.now(timezone.utc) - timedelta(days=1)
        s.commit()
    _flood_other_tenant_trips(120)
    ids = {t["proposal_id"] for t in client.get("/v1/tracking", headers=auth("shipper_a")).json()}
    assert prop["id"] in ids                                                       # trước đây bị cắt bởi LIMIT 100 rồi mới lọc quyền
    assert client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).status_code == 200


def test_benefits_listing_only_returns_rows_the_actor_may_see(client):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    assert post_event(client, "carrier_b", prop["id"], "TRIP_STARTED").status_code == 202
    run_worker(client)
    assert post_event(client, "carrier_b", prop["id"], "TRIP_COMPLETED", {"actual_empty_km": 12}).status_code == 202
    run_worker(client)
    mine = client.get("/v1/benefits", headers=auth("shipper_a")).json()
    assert [b["shipment_code"] for b in mine["items"]] == ["LOT-A-001"]
    assert client.get("/v1/benefits", headers=auth("node_c")).json()["items"] == []       # ICD không có quyền xem sổ lợi ích
    assert len(client.get("/v1/benefits", headers=auth("dispatch")).json()["items"]) == 1
