"""Test cho các sửa sau code review N1: validate đầu vào, cô lập mã lô theo tenant, ràng buộc DB, retime."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models as m
from app.db import SessionLocal
from app.matching import gates
from tests.conftest import auth

NOW = datetime.now(timezone.utc)
iso = lambda d: d.isoformat()  # noqa: E731


def _body(client, code="LOT-NEW", **over):
    locs = client.get("/v1/locations", headers=auth("shipper_a")).json()
    kcn = next(l["id"] for l in locs if l["kind"] == "industrial_zone")
    icd = next(l["id"] for l in locs if l["kind"] == "icd")
    body = {"code": code, "cargo_type": "dry", "weight_kg": 9000, "volume_m3": 22,
            "origin_location_id": kcn, "dest_location_id": icd,
            "ready_at": iso(NOW + timedelta(hours=1)), "pickup_deadline": iso(NOW + timedelta(hours=4)),
            "cutoff_at": iso(NOW + timedelta(hours=12))}
    return body | over


# ---- validate đầu vào: lỗi phải là 4xx, không bao giờ 500 ----
def test_naive_datetime_rejected_422(client):
    r = client.post("/v1/shipments", json=_body(client, ready_at="2030-01-01T00:00:00"), headers=auth("shipper_a"))
    assert r.status_code == 422


def test_unknown_location_rejected_422(client):
    r = client.post("/v1/shipments", json=_body(client, origin_location_id="00000000-0000-0000-0000-000000000000"),
                    headers=auth("shipper_a"))
    assert r.status_code == 422


@pytest.mark.parametrize("field,delta_h", [("cutoff_at", 2), ("pickup_deadline", 0)])
def test_time_order_enforced(client, field, delta_h):
    # cutoff trước pickup_deadline (cutoff=+2h < pickup=+4h) / pickup_deadline không sau ready_at
    over = {field: iso(NOW + timedelta(hours=delta_h if field == "cutoff_at" else 1))}
    r = client.post("/v1/shipments", json=_body(client, **over), headers=auth("shipper_a"))
    assert r.status_code == 422


# ---- mã lô unique theo tenant: không lộ lô của tổ chức khác ----
def test_lot_code_scoped_per_tenant(client):
    # A dùng lại mã của B → được phép (không lộ sự tồn tại của LOT-B-011), và không thấy lô của B
    r = client.post("/v1/shipments", json=_body(client, code="LOT-B-011"), headers=auth("shipper_a"))
    assert r.status_code == 201
    # trùng mã trong CHÍNH tenant → 409 sạch, không 500
    r2 = client.post("/v1/shipments", json=_body(client, code="LOT-B-011"), headers=auth("shipper_a"))
    assert r2.status_code == 409
    assert len(client.get("/v1/shipments", headers=auth("shipper_a")).json()) == 11  # 10 seed + 1 mới


# ---- ràng buộc DB cho booking (chuẩn bị N2) ----
@pytest.fixture()
def proposal_ids(seeded):
    with SessionLocal() as s:
        ship = s.execute(select(m.Shipment)).scalars().first()
        veh = s.execute(select(m.Vehicle)).scalars().first()
        ids = []
        for _ in range(2):
            p = m.Proposal(shipment_id=ship.id, vehicle_id=veh.id, rule_version="rules-v1",
                           assumption_version="assume-v2")
            s.add(p)
            s.flush()
            ids.append(p.id)
        s.commit()
        yield ids, veh.id


def _reserve(session, proposal_id, rtype, rid, status="held"):
    session.add(m.Reservation(proposal_id=proposal_id, resource_type=rtype, resource_id=rid,
                              status=status, expires_at=NOW + timedelta(seconds=120)))
    session.flush()


def test_vehicle_cannot_be_actively_reserved_twice(proposal_ids):
    (p1, p2), vehicle_id = proposal_ids
    with SessionLocal() as s:
        _reserve(s, p1, "vehicle", vehicle_id)
        s.commit()
    with SessionLocal() as s, pytest.raises(IntegrityError):
        _reserve(s, p2, "vehicle", vehicle_id)  # đặt trùng → DB chặn


def test_released_reservation_frees_the_resource(proposal_ids):
    (p1, p2), vehicle_id = proposal_ids
    with SessionLocal() as s:
        _reserve(s, p1, "vehicle", vehicle_id, status="released")
        _reserve(s, p2, "vehicle", vehicle_id, status="held")  # hợp lệ vì cái cũ đã released
        s.commit()


def test_slot_with_capacity_allows_multiple_reservations(proposal_ids, seeded):
    (p1, p2), _ = proposal_ids
    with SessionLocal() as s:
        slot = s.execute(select(m.Slot).where(m.Slot.remaining > 1)).scalars().first()
        _reserve(s, p1, "slot", slot.id)
        _reserve(s, p2, "slot", slot.id)  # slot nhiều chỗ: không bị unique chặn
        s.commit()


def test_invalid_status_rejected_by_db(proposal_ids):
    (p1, _), _ = proposal_ids
    with SessionLocal() as s, pytest.raises(IntegrityError):
        s.execute(m.Proposal.__table__.update().where(m.Proposal.id == p1).values(status="teleported"))
        s.flush()


def test_slot_remaining_cannot_go_negative(seeded):
    with SessionLocal() as s, pytest.raises(IntegrityError):
        slot = s.execute(select(m.Slot)).scalars().first()
        slot.remaining = -1
        s.flush()


# ---- retime: demo luôn tươi, không phụ thuộc giờ seed ----
def test_retime_makes_stale_fleet_fresh_again(client):
    with SessionLocal() as s:  # giả lập: seed đã 30 phút trước
        aset = s.execute(select(m.AssumptionSet)).scalars().first()
        aset.params = {**aset.params, "anchor_at": (NOW - timedelta(minutes=30)).isoformat()}
        for v in s.execute(select(m.Vehicle)).scalars():
            v.position_updated_at = v.position_updated_at - timedelta(minutes=30)
        s.commit()
    vehicles = client.get("/v1/vehicles", headers=auth("carrier_b")).json()
    assert all((NOW - datetime.fromisoformat(v["position_updated_at"])).total_seconds() > 25 * 60 for v in vehicles)

    assert client.post("/v1/demo/retime", headers=auth("dispatch")).status_code == 200
    vehicles = client.get("/v1/vehicles", headers=auth("carrier_b")).json()
    ages = sorted((datetime.now(timezone.utc) - datetime.fromisoformat(v["position_updated_at"])).total_seconds() / 60
                  for v in vehicles)
    assert ages[0] < 5          # xe bình thường lại tươi
    assert ages[-1] > 5          # xe cố ý quá hạn (22 phút) VẪN quá hạn → kịch bản "dữ liệu stale" giữ nguyên


@pytest.mark.parametrize("user", ["shipper_a", "carrier_b", "node_c"])
def test_retime_is_dispatcher_only(client, user):
    assert client.post("/v1/demo/retime", headers=auth(user)).status_code == 403


# ---- ranh giới stale của hard gate (now cố định, không phụ thuộc giờ chạy) ----
@pytest.mark.parametrize("age_min,expected", [(4.9, "PASS"), (5.0, "PASS"), (5.1, "FAIL")])
def test_stale_boundary(age_min, expected):
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    veh = SimpleNamespace(position_updated_at=now - timedelta(minutes=age_min))
    assert gates.gate_data_fresh(veh, now, {"stale_position_minutes": 5}).status == expected
