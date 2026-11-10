"""Booking (DRAFT 5.4, điều kiện qua Ngày 3): luồng xác nhận đến completed; 2 request đồng thời → chỉ 1 thành công."""
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app import models as m
from app.db import SessionLocal
from app.main import app
from tests.conftest import auth
from tests.helpers import act, confirm_all, get, match, post_event, run_worker, slot_remaining


def _first(client, code="LOT-A-001"):
    return match(client, "shipper_a", code)["proposals"][0]


def _concurrently(calls):
    """Chạy các lời gọi (user, proposal_id, version) cùng lúc bằng barrier; trả danh sách status code."""
    barrier, out = threading.Barrier(len(calls)), []

    def go(user, pid, version):
        c = TestClient(app, raise_server_exceptions=False)
        barrier.wait()
        r = c.post(f"/v1/proposals/{pid}/hold", json={"version": version},
                   headers={**auth(user), "Idempotency-Key": str(uuid.uuid4())})
        out.append(r.status_code)
    ts = [threading.Thread(target=go, args=c) for c in calls]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return sorted(out)


# ---------- luồng hợp lệ đến completed ----------
def test_full_flow_to_completed(client):
    prop = _first(client)
    assert prop["status"] == "proposed" and prop["my_actions"]["hold"] and not prop["my_actions"]["accept"]
    assert prop["slot"]["source"] == "mock" and prop["is_simulated"]
    before = slot_remaining(prop["slot"]["id"])

    held = act(client, "shipper_a", prop, "hold").json()
    assert held["status"] == "pending_acceptance" and 0 < held["hold_seconds_left"] <= 120
    assert slot_remaining(prop["slot"]["id"]) == before - 1

    confirmed = confirm_all(client, held)
    assert all(p["accepted"] for p in confirmed["parties"].values())
    assert confirmed["shipment"]["status"] == "matched"

    pid = prop["id"]
    assert post_event(client, "carrier_b", pid, "TRIP_STARTED").status_code == 202
    run_worker(client)
    assert get(client, "shipper_a", pid)["status"] == "executing"
    assert post_event(client, "carrier_b", pid, "TRIP_COMPLETED").status_code == 202
    run_worker(client)
    done = get(client, "shipper_a", pid)
    assert done["status"] == "completed" and done["shipment"]["status"] == "completed"
    with SessionLocal() as s:
        assert s.execute(select(m.Vehicle.status).where(m.Vehicle.id == uuid.UUID(done["vehicle"]["id"]))).scalar_one() == "available"
        assert {r.status for r in s.execute(select(m.Reservation).where(m.Reservation.proposal_id == uuid.UUID(pid))).scalars()} == {"released"}


# ---------- quyền xác nhận thuộc chủ thể ----------
def test_roles_and_party_permissions(client):
    prop = _first(client)
    assert act(client, "carrier_b", prop, "hold").status_code == 403   # carrier không giữ thay shipper
    assert act(client, "node_c", prop, "hold").status_code == 403
    assert act(client, "shipper_a", prop, "accept").status_code == 409  # chưa hold
    held = act(client, "dispatch", prop, "hold").json()                # điều phối viên được giữ
    assert held["status"] == "pending_acceptance"
    assert act(client, "dispatch", held["id"], "accept").status_code == 403  # nhưng KHÔNG xác nhận thay ai
    assert act(client, "node_c", held["id"], "accept").status_code == 200
    assert act(client, "node_c", held["id"], "accept").status_code == 409    # đã xác nhận phần node (key khác)
    view = get(client, "carrier_b", held["id"])
    assert view["my_actions"]["accept"] is True and view["parties"]["node"]["accepted"] is True


def test_forwarder_owns_both_carrier_and_shipper_party(client):
    prop = match(client, "carrier_b", "LOT-B-011")["proposals"][0]
    held = act(client, "carrier_b", prop, "hold").json()
    after_b = act(client, "carrier_b", held["id"], "accept").json()
    assert after_b["parties"]["carrier"]["accepted"] and after_b["parties"]["shipper"]["accepted"]
    assert act(client, "node_c", held["id"], "accept").json()["status"] == "confirmed"


def test_idempotency_key_and_version_are_required(client):
    prop = _first(client)
    r = client.post(f"/v1/proposals/{prop['id']}/hold", json={"version": prop["version"]}, headers=auth("shipper_a"))
    assert r.status_code == 400 and r.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert act(client, "shipper_a", prop, "hold", version=prop["version"] + 5).status_code == 409


def test_replayed_hold_has_no_second_effect(client):
    prop = _first(client)
    before = slot_remaining(prop["slot"]["id"])
    r1 = act(client, "shipper_a", prop, "hold", key="same-key")
    r2 = act(client, "shipper_a", prop, "hold", key="same-key")   # cùng key (kể cả version cũ)
    assert r1.status_code == r2.status_code == 200 and r2.headers.get("Idempotent-Replay") == "true"
    assert r1.json()["version"] == r2.json()["version"]
    assert slot_remaining(prop["slot"]["id"]) == before - 1
    with SessionLocal() as s:
        assert len(s.execute(select(m.Reservation).where(m.Reservation.proposal_id == uuid.UUID(prop["id"]))).scalars().all()) == 3
    assert act(client, "shipper_a", prop["id"], "reject", key="same-key").status_code == 422  # key dùng cho việc khác


# ---------- race condition ----------
def test_same_proposal_many_concurrent_holds_only_one_wins(client):
    prop = _first(client)
    codes = _concurrently([("shipper_a", prop["id"], prop["version"])] * 6)
    assert codes.count(200) == 1 and codes.count(409) == 5
    assert get(client, "shipper_a", prop["id"])["status"] == "pending_acceptance"


def test_two_proposals_same_vehicle_only_one_holds(client):
    ra, rb = match(client, "shipper_a", "LOT-A-001"), match(client, "shipper_a", "LOT-A-002")
    by_vehicle = {p["vehicle"]["id"]: p for p in rb["proposals"]}
    pa, pb = next((p, by_vehicle[p["vehicle"]["id"]]) for p in ra["proposals"] if p["vehicle"]["id"] in by_vehicle)
    codes = _concurrently([("shipper_a", pa["id"], pa["version"]), ("shipper_a", pb["id"], pb["version"])])
    assert codes == [200, 409]
    with SessionLocal() as s:  # không bao giờ có 2 reservation hiệu lực cho cùng xe
        active = s.execute(select(m.Reservation).where(
            m.Reservation.resource_type == "vehicle", m.Reservation.status.in_(("held", "committed")))).scalars().all()
        assert len(active) == 1


def test_last_slot_seat_goes_to_one_request_and_never_negative(client):
    pa = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    rb = match(client, "shipper_a", "LOT-A-002")["proposals"]
    pb = next(p for p in rb if p["vehicle"]["id"] != pa["vehicle"]["id"] and p["slot"]["id"] == pa["slot"]["id"]) \
        if any(p["vehicle"]["id"] != pa["vehicle"]["id"] and p["slot"]["id"] == pa["slot"]["id"] for p in rb) else None
    if pb is None:
        pytest.skip("two proposals did not share a slot in this seed timing")
    with SessionLocal() as s:  # còn đúng 1 chỗ
        s.execute(update(m.Slot).where(m.Slot.id == uuid.UUID(pa["slot"]["id"])).values(capacity=1, remaining=1))
        s.commit()
    codes = _concurrently([("shipper_a", pa["id"], pa["version"]), ("shipper_a", pb["id"], pb["version"])])
    assert codes == [200, 409]
    assert slot_remaining(pa["slot"]["id"]) == 0


# ---------- hết hạn, re-check, từ chối ----------
def _expire_now(proposal_id: str):
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    with SessionLocal() as s:
        s.execute(update(m.Reservation).where(m.Reservation.proposal_id == uuid.UUID(proposal_id)).values(expires_at=past))
        s.execute(update(m.Proposal).where(m.Proposal.id == uuid.UUID(proposal_id)).values(expires_at=past))
        s.commit()


def test_expired_hold_releases_resources_and_blocks_accept(client):
    prop = _first(client)
    before = slot_remaining(prop["slot"]["id"])
    held = act(client, "shipper_a", prop, "hold").json()
    _expire_now(held["id"])
    assert act(client, "node_c", held["id"], "accept").status_code == 409  # PROPOSAL_EXPIRED
    view = get(client, "shipper_a", held["id"])
    assert view["status"] == "expired" and not view["my_actions"]["accept"]
    assert slot_remaining(prop["slot"]["id"]) == before                    # chỗ slot được trả lại
    other = match(client, "shipper_a", "LOT-A-002")["proposals"][0]        # tài nguyên giữ lại dùng được
    assert act(client, "shipper_a", other, "hold").status_code == 200


def test_final_confirmation_rechecks_and_releases_on_failure(client):
    prop = _first(client)
    before = slot_remaining(prop["slot"]["id"])
    held = act(client, "shipper_a", prop, "hold").json()
    assert act(client, "carrier_b", held["id"], "accept").status_code == 200
    assert act(client, "shipper_a", held["id"], "accept").status_code == 200
    with SessionLocal() as s:  # vị trí xe quá hạn ngay trước xác nhận cuối
        s.execute(update(m.Vehicle).where(m.Vehicle.id == uuid.UUID(prop["vehicle"]["id"]))
                  .values(position_updated_at=datetime.now(timezone.utc) - timedelta(minutes=30)))
        s.commit()
    r = act(client, "node_c", held["id"], "accept")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "RECHECK_FAILED"
    assert any(x["reason_code"] == "DATA_STALE" for x in r.json()["detail"]["reasons"])
    view = get(client, "shipper_a", held["id"])
    assert view["status"] == "cancelled"                       # không xác nhận khi re-check thất bại
    assert slot_remaining(prop["slot"]["id"]) == before        # holds được giải phóng
    with SessionLocal() as s:
        assert s.execute(select(m.Shipment.status).where(m.Shipment.id == uuid.UUID(prop["shipment"]["id"]))).scalar_one() == "open"


def test_reject_releases_hold(client):
    prop = _first(client)
    before = slot_remaining(prop["slot"]["id"])
    held = act(client, "shipper_a", prop, "hold").json()
    assert act(client, "node_c", held["id"], "reject").json()["status"] == "rejected"
    assert slot_remaining(prop["slot"]["id"]) == before
    assert act(client, "shipper_a", held["id"], "hold").status_code == 409  # không hồi sinh đề xuất đã từ chối


def test_vehicle_in_use_is_excluded_from_new_matches(client):
    confirm_all(client, _first(client))
    other = match(client, "shipper_a", "LOT-A-002")
    used = {r["plate"] for r in other["rejections"] if any(x["reason_code"] == "VEHICLE_UNAVAILABLE" for x in r["reasons"])}
    assert len(used) >= 2  # 51C-100.10 (offline) + xe vừa được cam kết


def test_retime_expires_open_holds_and_restores_slots(client):
    prop = _first(client)
    before = slot_remaining(prop["slot"]["id"])
    held = act(client, "shipper_a", prop, "hold").json()
    assert client.post("/v1/demo/retime", headers=auth("dispatch")).status_code == 200
    assert get(client, "shipper_a", held["id"])["status"] == "expired"
    assert slot_remaining(prop["slot"]["id"]) == before
