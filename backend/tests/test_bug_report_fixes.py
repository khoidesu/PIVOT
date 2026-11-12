"""Hồi quy cho BUG_REPORT_HANDOFF (12/11/2026): BUG-01 placeholder SLOT_WINDOW_MISSED, BUG-02 carrier tạo lô,
BUG-03 so tải 1.000 kg / 30 m³, BUG-04 preflight, BUG-05 completion → ledger."""
import uuid
from datetime import datetime, timedelta, timezone

from tests.conftest import auth


def _body(client, **over):
    now = datetime.now(timezone.utc)
    locs = client.get("/v1/locations", headers=auth("shipper_a")).json()
    kcn = next(l["id"] for l in locs if l["kind"] == "industrial_zone")
    icd = next(l["id"] for l in locs if l["kind"] == "icd")
    body = {"code": f"LOT-{uuid.uuid4().hex[:6]}", "cargo_type": "dry", "weight_kg": 1000, "volume_m3": 30,
            "origin_location_id": kcn, "dest_location_id": icd,
            "ready_at": (now + timedelta(hours=1)).isoformat(), "pickup_deadline": (now + timedelta(hours=4)).isoformat(),
            "cutoff_at": (now + timedelta(hours=12)).isoformat()}
    return body | over


def _new_lot(client, **over):
    r = client.post("/v1/shipments", headers=auth("shipper_a"), json=_body(client, **over))
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _run(client, user, sid):
    r = client.post("/v1/match-runs", json={"shipment_id": sid}, headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()


# ---------- BUG-03 ----------
def test_bug03_1000kg_30m3_only_fails_capacity_on_25m3_vehicles(client):
    run = _run(client, "dispatch", _new_lot(client))
    cap = {r["plate"]: x["detail"] for r in run["rejections"] for x in r["reasons"] if x["reason_code"] == "CAPACITY_EXCEEDED"}
    assert set(cap) == {"51C-100.05", "51C-100.06"}, cap          # chỉ hai xe 8 t / 25 m³
    for d in cap.values():
        assert d["over"] == ["volume"] and d["capacity_m3"] == 25
    passed = {p["vehicle"]["plate"] for p in run["proposals"]}
    assert passed and passed <= {"51C-100.01", "51C-100.02", "51C-100.03", "51C-100.04"}


def test_bug03_kg_only_m3_only_and_equal_capacity_edges():
    from types import SimpleNamespace as NS
    from app.matching import gates
    veh = NS(capacity_kg=8000, capacity_m3=25)
    cases = [((8001, 10), "FAIL", ["weight"]), ((1000, 25.5), "FAIL", ["volume"]), ((9000, 30), "FAIL", ["weight", "volume"]),
             ((8000, 25), "PASS", []), ((7999, 24.9), "PASS", [])]
    for (kg, m3), status, over in cases:
        r = gates.gate_capacity(NS(weight_kg=kg, volume_m3=m3), veh)
        assert (r.status, r.detail["over"]) == (status, over), (kg, m3)
    big = gates.gate_capacity(NS(weight_kg=1000, volume_m3=30), NS(capacity_kg=24000, capacity_m3=60))
    assert big.status == "PASS"


def test_bug03_shipper_sees_volume_vs_weight_but_not_vehicle_capacity(client):
    run = _run(client, "shipper_a", _new_lot(client))
    caps = [x["detail"] for r in run["rejections"] for x in r["reasons"] if x["reason_code"] == "CAPACITY_EXCEEDED"]
    assert len(caps) == 2
    for d in caps:
        assert d["over"] == ["volume"] and d["redacted"] is True and "capacity_m3" not in d and "capacity_kg" not in d


# ---------- BUG-01 ----------
def _slot_missed(run):
    return [x["detail"] for r in run["rejections"] for x in r["reasons"] if x["reason_code"] == "SLOT_WINDOW_MISSED"]


def test_bug01_slot_window_missed_keeps_slot_end_for_shipper_but_not_fleet_eta(client):
    # cut-off xa nhưng slot (seed: 2h–12h tới) kết thúc trước khi xe tới ICD → SLOT_WINDOW_MISSED
    now = datetime.now(timezone.utc)
    sid = _new_lot(client, volume_m3=10, ready_at=(now + timedelta(hours=11, minutes=30)).isoformat(),
                   pickup_deadline=(now + timedelta(hours=14)).isoformat(), cutoff_at=(now + timedelta(hours=30)).isoformat())
    shipper = _slot_missed(_run(client, "shipper_a", sid))
    assert shipper, "cần ít nhất một xe trượt khung slot để kiểm tra"
    for d in shipper:
        assert d["redacted"] is True and "slot_end_at" in d and "eta_icd" not in d   # giờ slot: có; ETA xe bên khác: không
        assert not {"remaining", "slot_id", "capacity_kg", "status"} & set(d)
    full = _slot_missed(_run(client, "dispatch", sid))
    assert full and all("eta_icd" in d and "slot_end_at" in d for d in full)


# ---------- BUG-02 ----------
def test_bug02_carrier_cannot_create_update_or_cancel_shipments(client):
    assert client.post("/v1/shipments", headers=auth("carrier_b"), json=_body(client)).status_code == 403
    own = next(s for s in client.get("/v1/shipments", headers=auth("carrier_b")).json()
               if s["tenant_id"] and s["status"] == "open")
    assert client.patch(f"/v1/shipments/{own['id']}", headers=auth("carrier_b"),
                        json={"weight_kg": 1, "version": own["version"]}).status_code == 403
    assert client.delete(f"/v1/shipments/{own['id']}", headers=auth("carrier_b")).status_code == 403
    # vẫn: xác nhận dữ liệu lô sẵn có còn đúng, chạy ghép, nhận chuyến
    assert client.post(f"/v1/shipments/{own['id']}/refresh", headers=auth("carrier_b")).status_code == 200
    assert _run(client, "carrier_b", own["id"])["evaluated_vehicles"] >= 1
    # chủ hàng vẫn tạo/sửa/huỷ bình thường
    sid = _new_lot(client)
    lot = client.get(f"/v1/shipments/{sid}", headers=auth("shipper_a")).json()
    assert client.patch(f"/v1/shipments/{sid}", headers=auth("shipper_a"), json={"weight_kg": 900, "version": lot["version"]}).status_code == 200
    assert client.delete(f"/v1/shipments/{sid}", headers=auth("shipper_a")).status_code == 200


# ---------- BUG-04 ----------
def test_bug04_refreshing_data_does_not_clear_passed_deadlines(client):
    from sqlalchemy import update
    from app import models as m
    from app.db import SessionLocal
    sid = _new_lot(client)
    past = datetime.now(timezone.utc) - timedelta(hours=20)
    with SessionLocal() as s:  # như ảnh #5: dữ liệu ~1.773 phút, mọi mốc đã qua
        s.execute(update(m.Shipment).where(m.Shipment.id == uuid.UUID(sid)).values(
            data_updated_at=past - timedelta(minutes=600), ready_at=past, pickup_deadline=past + timedelta(hours=2),
            cutoff_at=past + timedelta(hours=8)))
        s.commit()
    before = {x["reason_code"] for r in _run(client, "shipper_a", sid)["rejections"] for x in r["reasons"]}
    assert {"DATA_STALE", "PICKUP_WINDOW_MISSED", "CUTOFF_RISK"} <= before
    assert client.post(f"/v1/shipments/{sid}/refresh", headers=auth("shipper_a")).status_code == 200
    run = _run(client, "shipper_a", sid)
    after = [x for r in run["rejections"] for x in r["reasons"]]
    assert not any(x["reason_code"] == "DATA_STALE" and x["gate"] == "shipment_fresh" for x in after)   # làm mới chỉ xử lý tuổi dữ liệu
    assert {"PICKUP_WINDOW_MISSED", "CUTOFF_RISK"} <= {x["reason_code"] for x in after}               # mốc đã qua vẫn bị loại
    assert run["status"] == "no_feasible_option"
    assert client.get("/v1/meta", headers=auth("shipper_a")).json()["stale_shipment_minutes"] == 60


# ---------- BUG-05 ----------
def test_bug05_arrival_and_unload_do_not_record_benefit_only_trip_completed_does(client):
    from tests.helpers import confirm_all, match, post_event, run_worker
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    confirm_all(client, prop)
    pid = prop["id"]
    ledger = lambda: client.get("/v1/benefits", headers=auth("shipper_a")).json()["items"]
    post_event(client, "carrier_b", pid, "TRIP_STARTED"); run_worker(client)
    post_event(client, "carrier_b", pid, "GATE_CHECK_IN"); run_worker(client)
    post_event(client, "node_c", pid, "UNLOAD_STARTED"); run_worker(client)
    post_event(client, "node_c", pid, "UNLOAD_COMPLETED"); run_worker(client)
    assert ledger() == []                                                        # tới ICD + dỡ xong: chưa phải hoàn tất chuyến
    for _ in range(2):                                                            # gửi lặp không nhân đôi
        post_event(client, "carrier_b", pid, "TRIP_COMPLETED", {"actual_empty_km": 4.2}); run_worker(client)
    rows = ledger()
    assert len(rows) == 1 and rows[0]["status"] == "measured"
