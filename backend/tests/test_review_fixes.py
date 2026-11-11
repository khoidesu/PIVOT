"""Hồi quy cho hai lỗi nghiệp vụ tìm thấy khi rà soát (11/11/2026):
A1. slot / khung dock bắt đầu SAU cut-off của lô vẫn được đề xuất;
A2. tuổi dữ liệu vị trí xe bị đo bằng đồng hồ máy khách (đồng hồ chậm → vị trí vừa gửi bị coi là cũ)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import models as m
from app.db import SessionLocal
from app.matching import gates
from tests.conftest import auth
from tests.helpers import confirm_all, lot_id, match, run_worker
from tests.test_vehicle_events import NOW, position_age, vevent, vid


def _cutoff(client, code="LOT-A-001"):
    with SessionLocal() as s:
        return s.get(m.Shipment, uuid.UUID(lot_id(client, "shipper_a", code))).cutoff_at


def _move_slots(start, minutes=30):
    with SessionLocal() as s:
        for sl in s.execute(select(m.Slot)).scalars():
            sl.start_at, sl.end_at = start, start + timedelta(minutes=minutes)
        s.commit()


# ---------------------------------------------------------------- A1
@pytest.fixture()
def gate_world(seeded):
    with SessionLocal() as s:
        params = s.execute(select(m.AssumptionSet)).scalars().first().params
        ship = s.execute(select(m.Shipment).where(m.Shipment.code == "LOT-A-001")).scalars().first()
        veh = s.execute(select(m.Vehicle).where(m.Vehicle.plate == "51C-100.01")).scalars().first()
        win = s.execute(select(m.AvailabilityWindow).where(m.AvailabilityWindow.vehicle_id == veh.id)).scalars().first()
        slot = s.execute(select(m.Slot).order_by(m.Slot.start_at)).scalars().first()
        yield ship, win, slot, params, datetime.now(timezone.utc)


def test_gate_slot_rejects_a_slot_that_starts_after_the_cutoff(gate_world):
    ship, win, slot, params, now = gate_world
    slot.start_at, slot.end_at = ship.cutoff_at + timedelta(minutes=1), ship.cutoff_at + timedelta(minutes=31)
    r = gates.gate_slot(slot, ship, win, now, params)
    assert (r.status, r.reason_code) == ("FAIL", gates.SLOT_AFTER_CUTOFF)
    assert r.detail["cutoff_at"] and r.detail["slot_start_at"]


def test_gate_slot_accepts_a_slot_starting_exactly_at_the_cutoff(gate_world):
    ship, win, slot, params, now = gate_world
    slot.start_at, slot.end_at = ship.cutoff_at, ship.cutoff_at + timedelta(minutes=30)
    assert gates.gate_slot(slot, ship, win, now, params).reason_code != gates.SLOT_AFTER_CUTOFF


def test_no_proposal_when_every_slot_is_after_the_cutoff(client):
    cut = _cutoff(client)
    _move_slots(cut + timedelta(hours=1))
    run = match(client, "shipper_a", "LOT-A-001")
    assert run["status"] == "no_feasible_option" and run["proposals"] == []
    codes = {x["reason_code"] for r in run["rejections"] for x in r["reasons"]}
    assert "SLOT_AFTER_CUTOFF" in codes                                  # lý do hiển thị được, không âm thầm


def test_matching_picks_a_slot_before_the_cutoff_when_one_exists(client):
    cut = _cutoff(client)
    _move_slots(cut + timedelta(hours=1))
    with SessionLocal() as s:                                            # một slot hợp lệ, nằm sau thời điểm xe tới ICD
        ok = s.execute(select(m.Slot).order_by(m.Slot.id)).scalars().first()
        ok.start_at, ok.end_at = cut - timedelta(minutes=40), cut - timedelta(minutes=10)
        ok.remaining = ok.capacity = 3
        ok_id = str(ok.id)
        s.commit()
    run = match(client, "shipper_a", "LOT-A-001")
    assert run["status"] == "proposals"
    assert {p["slot"]["id"] for p in run["proposals"]} == {ok_id}
    assert all(datetime.fromisoformat(p["slot"]["start_at"].replace("Z", "+00:00")) <= cut for p in run["proposals"])


def test_dock_window_never_starts_after_the_cutoff(client):
    """Xác nhận đủ 3 bên: khung dock tự xếp phải bắt đầu trước cut-off; nếu không có khung thì mở DOCK_CONGESTION."""
    run = match(client, "shipper_a", "LOT-A-001")
    prop = confirm_all(client, run["proposals"][0])
    cut = _cutoff(client)
    with SessionLocal() as s:
        appt = s.execute(select(m.DockAppointment).where(m.DockAppointment.proposal_id == uuid.UUID(prop["id"]))).scalar_one_or_none()
        if appt is not None:
            assert appt.window_start <= cut
        else:
            ex = s.execute(select(m.ExceptionRecord).where(m.ExceptionRecord.proposal_id == uuid.UUID(prop["id"]))).scalars().all()
            assert any(e.exc_type == "DOCK_CONGESTION" for e in ex)


def test_dock_without_a_window_before_cutoff_raises_congestion_instead_of_booking_late(client):
    """Slot và cut-off hợp lệ, nhưng mọi dock kín tới sau cut-off → KHÔNG đặt lịch muộn; mở ngoại lệ DOCK_CONGESTION cho ICD quyết."""
    run = match(client, "shipper_a", "LOT-A-001")
    first = run["proposals"][0]
    arrive = datetime.fromisoformat(next(g for g in first["gates"] if g["gate"] == "cutoff")["detail"]["eta_icd"])
    cutoff = arrive + timedelta(minutes=5)                                  # vẫn đạt re-check cuối (xe tới trước cut-off)
    assert client.post(f"/v1/proposals/{first['id']}/hold", json={"version": first["version"]},
                       headers={**auth("shipper_a"), "Idempotency-Key": str(uuid.uuid4())}).status_code == 200
    with SessionLocal() as s:
        prop = s.get(m.Proposal, uuid.UUID(first["id"]))
        slot, ship = s.get(m.Slot, prop.slot_id), s.get(m.Shipment, prop.shipment_id)
        slot.start_at, slot.end_at = arrive - timedelta(minutes=10), arrive + timedelta(minutes=40)
        ship.cutoff_at = cutoff
        others = [uuid.UUID(p["id"]) for p in run["proposals"][1:]]          # mượn id đề xuất khác để thoả khoá ngoại của lịch "bận"
        docks = list(s.execute(select(m.Dock).where(m.Dock.node_org_id == slot.node_org_id).order_by(m.Dock.code)).scalars())
        assert 0 < len(docks) <= len(others)
        for d, other in zip(docks, others):                                 # dock kín từ trước slot tới 1 giờ SAU cut-off
            s.add(m.DockAppointment(dock_id=d.id, proposal_id=other, vehicle_id=prop.vehicle_id, window_start=slot.start_at - timedelta(hours=2),
                                    window_end=cutoff + timedelta(hours=1), status="scheduled", created_at=datetime.now(timezone.utc)))
        s.commit()
    for user in ("carrier_b", "shipper_a", "node_c"):
        v = client.get(f"/v1/proposals/{first['id']}", headers=auth(user)).json()["version"]
        r = client.post(f"/v1/proposals/{first['id']}/accept", json={"version": v}, headers={**auth(user), "Idempotency-Key": str(uuid.uuid4())})
        assert r.status_code == 200, r.text
    with SessionLocal() as s:
        assert s.get(m.Proposal, uuid.UUID(first["id"])).status == "confirmed"   # chuyến vẫn cam kết, chỉ thiếu lịch dock
        mine = s.execute(select(m.DockAppointment).where(m.DockAppointment.proposal_id == uuid.UUID(first["id"]))).scalars().all()
        assert mine == []                                                       # không có lịch bắt đầu sau cut-off
        ex = s.execute(select(m.ExceptionRecord).where(m.ExceptionRecord.proposal_id == uuid.UUID(first["id"]))).scalars().all()
        assert any(e.exc_type == "DOCK_CONGESTION" for e in ex)


# ---------------------------------------------------------------- A2
def _age(vehicle_id) -> timedelta:
    return datetime.now(timezone.utc) - position_age(vehicle_id)


def test_slow_client_clock_still_counts_as_a_fresh_position(client):
    v = vid(client, "51C-100.08")                                           # seed: vị trí cũ 22 phút
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", at=NOW() - timedelta(minutes=10)).status_code == 202
    run_worker(client)
    assert _age(v) < timedelta(minutes=1)                                   # đo theo giờ máy chủ khi nhận
    run = match(client, "dispatch", "LOT-A-001")
    assert not any(r["plate"] == "51C-100.08" and any(x["gate"] == "data_fresh" for x in r["reasons"]) for r in run["rejections"])


def test_fast_client_clock_never_produces_a_future_position_age(client):
    v = vid(client, "51C-100.08")
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", at=NOW() + timedelta(minutes=4)).status_code == 202
    run_worker(client)
    assert timedelta(0) <= _age(v) < timedelta(minutes=1)                   # không bao giờ nằm trong tương lai


def test_a_genuinely_old_position_is_still_old(client):
    """Tin đến muộn thật (cũ hơn ngưỡng chịu lệch) vẫn tính theo giờ xảy ra → vẫn bị coi là cũ."""
    v = vid(client, "51C-100.08")                                           # seed: 22 phút → tin 20 phút trước mới hơn dữ liệu hiện có
    assert vevent(client, "carrier_b", v, "VEHICLE_POSITION", at=NOW() - timedelta(minutes=20)).status_code == 202
    run_worker(client)
    assert timedelta(minutes=19) < _age(v) < timedelta(minutes=21)


def test_event_order_is_judged_by_event_time_not_by_arrival_time(client):
    v = vid(client, "51C-100.08")
    first = vevent(client, "carrier_b", v, "VEHICLE_POSITION", at=NOW() - timedelta(minutes=10))
    run_worker(client)
    applied = position_age(v)
    older = vevent(client, "carrier_b", v, "VEHICLE_POSITION", at=NOW() - timedelta(minutes=12))
    newer = vevent(client, "carrier_b", v, "VEHICLE_POSITION", at=NOW() - timedelta(minutes=9))
    run_worker(client)
    with SessionLocal() as s:
        assert s.get(m.Event, uuid.UUID(first.json()["event_id"])).quality_status == "applied"
        assert s.get(m.Event, uuid.UUID(older.json()["event_id"])).quality_status == "late"      # xảy ra trước tin đã áp dụng
        assert s.get(m.Event, uuid.UUID(newer.json()["event_id"])).quality_status == "applied"
    assert position_age(v) >= applied
