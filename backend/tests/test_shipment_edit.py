"""Sửa / huỷ yêu cầu: quyền, khoá lạc quan, khoá khi đã giữ/cam kết, làm mới dữ liệu, vô hiệu đề xuất cũ."""
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app import models as m
from app.db import SessionLocal
from app.main import app
from tests.conftest import auth
from tests.helpers import act, confirm_all, get, lot_id, match


def _lot(client, code="LOT-A-001", user="shipper_a"):
    return next(s for s in client.get("/v1/shipments", headers=auth(user)).json() if s["code"] == code)


def _patch(client, lot, user="shipper_a", **changes):
    return client.patch(f"/v1/shipments/{lot['id']}", json={"version": lot["version"], **changes}, headers=auth(user))


def test_owner_can_edit_and_data_is_refreshed(client):
    lot = _lot(client)
    with SessionLocal() as s:  # lô đã cũ: dữ liệu quá hạn
        s.execute(update(m.Shipment).where(m.Shipment.id == uuid.UUID(lot["id"])).values(data_updated_at=datetime.now(timezone.utc) - timedelta(hours=3)))
        s.commit()
    assert match(client, "shipper_a", "LOT-A-001")["status"] == "no_feasible_option"   # DATA_STALE của lô
    lot = _lot(client)
    r = _patch(client, lot, weight_kg=11000, customer_name="Khách mới")
    assert r.status_code == 200 and r.json()["weight_kg"] == 11000 and r.json()["version"] == lot["version"] + 1
    assert r.json()["customer_name"] == "Khách mới"
    assert match(client, "shipper_a", "LOT-A-001")["status"] == "proposals"           # sửa xong = dữ liệu tươi, ghép được


def test_fixing_a_lot_with_missing_data_makes_it_matchable(client):
    lot = _lot(client, "LOT-A-007")                                                   # thiếu trọng lượng/thể tích
    assert match(client, "shipper_a", "LOT-A-007")["status"] == "needs_data"
    r = _patch(client, lot, weight_kg=9000, volume_m3=24)
    assert r.status_code == 200 and r.json()["missing_fields"] == []
    assert match(client, "shipper_a", "LOT-A-007")["status"] == "proposals"


def test_only_the_owner_may_edit_or_cancel(client):
    lot = _lot(client)
    assert _patch(client, lot, user="carrier_b", weight_kg=1).status_code == 404       # tổ chức khác không thấy lô
    assert _patch(client, lot, user="node_c", weight_kg=1).status_code == 404
    assert _patch(client, lot, user="dispatch", weight_kg=1).status_code == 403        # điều phối viên thấy nhưng không sửa
    assert client.delete(f"/v1/shipments/{lot['id']}", headers=auth("dispatch")).status_code == 403
    assert client.delete(f"/v1/shipments/{lot['id']}", headers=auth("carrier_b")).status_code == 404
    assert _patch(client, lot, user="shipper_a2", weight_kg=8000).status_code == 200   # cùng tổ chức A: được


def test_optimistic_locking_and_validation(client):
    lot = _lot(client)
    assert client.patch(f"/v1/shipments/{lot['id']}", json={"version": 99, "weight_kg": 5}, headers=auth("shipper_a")).json()["detail"]["code"] == "VERSION_CONFLICT"
    assert _patch(client, lot, weight_kg=-1).status_code == 422
    assert client.patch(f"/v1/shipments/{lot['id']}", json={"version": lot["version"]}, headers=auth("shipper_a")).status_code == 422   # không có gì để sửa
    bad_order = _patch(client, lot, cutoff_at=(datetime.now(timezone.utc)).isoformat())
    assert bad_order.status_code == 422
    assert _patch(client, lot, origin_location_id=str(uuid.uuid4())).status_code == 422
    assert _patch(client, lot, ready_at="2030-01-01T00:00:00").status_code == 422     # thiếu múi giờ
    assert _lot(client)["version"] == lot["version"]                                  # sửa lỗi không làm đổi gì


def test_edit_invalidates_stale_proposals_but_is_blocked_by_hold_or_commitment(client):
    run = match(client, "shipper_a", "LOT-A-001")
    ids = [p["id"] for p in run["proposals"]]
    lot = _lot(client)
    assert _patch(client, lot, volume_m3=31).status_code == 200
    for pid in ids:                                                                   # đề xuất dựng trên dữ liệu cũ không còn hiệu lực
        assert get(client, "shipper_a", pid)["status"] == "cancelled"
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    act(client, "shipper_a", prop, "hold")
    lot = _lot(client)
    r = _patch(client, lot, weight_kg=500)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SHIPMENT_LOCKED"   # đang giữ chỗ
    assert client.delete(f"/v1/shipments/{lot['id']}", headers=auth("shipper_a")).status_code == 409
    confirm_all(client, get(client, "shipper_a", prop["id"]))
    lot = _lot(client)
    assert _patch(client, lot, weight_kg=500).json()["detail"]["code"] == "SHIPMENT_LOCKED"   # đã cam kết: phải qua ngoại lệ


def test_cancel_is_a_soft_delete_that_keeps_the_audit_trail(client):
    lot = _lot(client, "LOT-A-002")
    prop = match(client, "shipper_a", "LOT-A-002")["proposals"][0]
    r = client.delete(f"/v1/shipments/{lot['id']}", headers=auth("shipper_a"))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.delete(f"/v1/shipments/{lot['id']}", headers=auth("shipper_a")).status_code == 200   # idempotent
    assert _lot(client, "LOT-A-002")["status"] == "cancelled"                          # vẫn còn (không xoá cứng)
    assert get(client, "shipper_a", prop["id"])["status"] == "cancelled"
    assert client.post("/v1/match-runs", json={"shipment_id": lot["id"]}, headers=auth("shipper_a")).status_code == 409
    assert _patch(client, _lot(client, "LOT-A-002"), weight_kg=3).json()["detail"]["code"] == "SHIPMENT_LOCKED"
    with SessionLocal() as s:
        types = [e.event_type for e in s.execute(select(m.Event).where(m.Event.entity_id == uuid.UUID(lot["id"]))).scalars()]
        assert "SHIPMENT_CANCELLED" in types


def test_audit_event_records_field_names_not_sensitive_values(client):
    lot = _lot(client)
    _patch(client, lot, price_vnd=123456789, customer_name="Bí mật", weight_kg=10000)
    with SessionLocal() as s:
        ev = s.execute(select(m.Event).where(m.Event.event_type == "SHIPMENT_UPDATED")).scalars().one()
        assert set(ev.payload["fields"]) == {"price_vnd", "customer_name", "weight_kg"}
        assert "123456789" not in str(ev.payload) and "Bí mật" not in str(ev.payload)
        assert set(ev.payload["sensitive_fields_changed"]) == {"price_vnd", "customer_name"}


def test_concurrent_edit_and_hold_never_corrupt_state(client):
    """Sửa và giữ chỗ cùng lúc: hoặc sửa thắng (đề xuất bị huỷ → hold 409) hoặc hold thắng (sửa 409). Không deadlock/500."""
    for _ in range(4):
        prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
        lot, out, barrier = _lot(client), [], threading.Barrier(2)

        def edit():
            c = TestClient(app, raise_server_exceptions=False); barrier.wait()
            out.append(("edit", c.patch(f"/v1/shipments/{lot['id']}", json={"version": lot["version"], "weight_kg": 10000 + len(out)}, headers=auth("shipper_a")).status_code))

        def hold():
            c = TestClient(app, raise_server_exceptions=False); barrier.wait()
            out.append(("hold", c.post(f"/v1/proposals/{prop['id']}/hold", json={"version": prop["version"]}, headers={**auth("shipper_a"), "Idempotency-Key": str(uuid.uuid4())}).status_code))
        ts = [threading.Thread(target=edit), threading.Thread(target=hold)]
        [t.start() for t in ts]; [t.join() for t in ts]
        codes = dict(out)
        assert 500 not in codes.values() and 503 not in codes.values(), out
        assert (codes["edit"], codes["hold"]) in {(200, 409), (409, 200)}, out
        client.post("/v1/demo/reset", headers=auth("dispatch"))


def _age_lot(lot, hours=3):
    with SessionLocal() as s:
        s.execute(update(m.Shipment).where(m.Shipment.id == uuid.UUID(lot["id"])).values(data_updated_at=datetime.now(timezone.utc) - timedelta(hours=hours)))
        s.commit()


def test_owner_can_refresh_a_stale_lot_without_changing_it(client):
    """Tester không có mã quản trị: chủ lô xác nhận 'dữ liệu còn đúng' để qua cổng shipment_fresh."""
    lot = _lot(client)
    _age_lot(lot)
    assert match(client, "shipper_a", "LOT-A-001")["status"] == "no_feasible_option"
    r = client.post(f"/v1/shipments/{lot['id']}/refresh", headers=auth("shipper_a"))
    assert r.status_code == 200
    after = r.json()
    assert (after["version"], after["weight_kg"], after["status"]) == (lot["version"], lot["weight_kg"], "open")   # nội dung/version không đổi
    assert after["data_updated_at"] > lot["data_updated_at"]
    assert match(client, "shipper_a", "LOT-A-001")["status"] == "proposals"
    with SessionLocal() as s:  # có vết audit, không ghi giá/khách hàng
        ev = s.execute(select(m.Event).where(m.Event.entity_id == uuid.UUID(lot["id"]), m.Event.event_type == "SHIPMENT_REFRESHED")).scalars().all()
        assert len(ev) == 1 and set(ev[0].payload) == {"version"}


def test_refresh_is_owner_only_and_blocked_once_held(client):
    lot = _lot(client)
    assert client.post(f"/v1/shipments/{lot['id']}/refresh", headers=auth("carrier_b")).status_code == 404    # không thấy lô
    assert client.post(f"/v1/shipments/{lot['id']}/refresh", headers=auth("dispatch")).status_code == 403    # thấy nhưng không phải chủ
    assert client.post(f"/v1/shipments/{lot['id']}/refresh", headers=auth("shipper_a2")).status_code == 200   # cùng tổ chức A
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    assert act(client, "shipper_a", prop, "hold").status_code == 200
    assert client.post(f"/v1/shipments/{lot['id']}/refresh", headers=auth("shipper_a")).status_code == 409   # đã giữ → khoá
    assert client.post(f"/v1/shipments/{uuid.uuid4()}/refresh", headers=auth("shipper_a")).status_code == 404
