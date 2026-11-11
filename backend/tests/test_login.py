"""Đăng nhập đơn giản (tên + vai trò): mỗi người một tổ chức riêng + dữ liệu mẫu; mỗi tab một người."""
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app import accounts
from app import models as m
from app.config import settings
from app.db import SessionLocal
from app.main import app
from tests.conftest import auth


def login(client, name, role):
    r = client.post("/v1/auth/login", json={"name": name, "role": role})
    return r


def as_(client, name, role):
    """Đăng nhập và trả (token, me)."""
    r = login(client, name, role)
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["me"]


def get(client, token, path):
    return client.get(path, headers=auth(token))


def lots(client, token):
    return get(client, token, "/v1/shipments").json()


# ---------- đăng nhập ----------
def test_invalid_role_or_name_is_rejected(client):
    assert login(client, "Hoa", "admin").json()["detail"]["code"] == "INVALID_ROLE"
    for bad in ("", " ", "A", "x" * 41, "<script>", "Hoa;DROP", "---", "💥💥"):
        r = login(client, bad, "shipper")
        assert r.status_code == 422, bad
    assert login(client, "Hoa", "shipper").status_code == 200


def test_me_reflects_the_chosen_name_and_role(client):
    token, me = as_(client, "Hoa", "shipper")
    assert me["user_name"] == "Hoa" and me["role"] == "shipper" and me["org_name"] == "Hoa · Chủ hàng"
    assert get(client, token, "/v1/me").json()["org_id"] == me["org_id"]
    assert client.get("/v1/me", headers=auth("khong-ton-tai")).status_code == 401


def test_each_new_person_gets_their_own_org_and_role_specific_sample_data(client):
    ts, shipper = as_(client, "Hoa", "shipper")
    tc, carrier = as_(client, "Lan", "carrier")
    tn, node = as_(client, "Cường", "node_operator")
    td, disp = as_(client, "Tâm", "dispatcher")
    assert len({shipper["org_id"], carrier["org_id"], node["org_id"], disp["org_id"]}) == 4
    assert len(lots(client, ts)) == 4 and all(x["is_simulated"] for x in lots(client, ts))
    assert len(get(client, tc, "/v1/vehicles").json()) == 4
    assert get(client, tn, "/v1/shipments").json() == []                      # ICD không có lô, chỉ có slot
    mine = [x for x in get(client, tn, "/v1/slots").json() if x["node_org_id"] == node["org_id"]]
    assert len(mine) == 8 and all(x["source"] == "mock" for x in mine)
    assert get(client, td, "/v1/vehicles").status_code == 200                  # điều phối viên xem được mọi thứ nhưng không có dữ liệu riêng
    assert lots(client, tc) == []                                              # nhà vận tải mới không có lô


def test_logging_in_again_returns_the_same_account(client):
    t1, a = as_(client, "Hoa", "shipper")
    r = login(client, "  hoa ", "shipper").json()                              # khoảng trắng/hoa-thường không tạo người mới
    assert r["token"] == t1 and r["is_new"] is False and r["me"]["org_id"] == a["org_id"]
    assert login(client, "Hòa", "shipper").json()["token"] == t1                # khác dấu → cùng tài khoản (ghi chú trong tài liệu)
    assert len(lots(client, t1)) == 4                                           # đăng nhập lại không nhân đôi dữ liệu mẫu
    assert as_(client, "Hoa", "carrier")[1]["org_id"] != a["org_id"]            # cùng tên khác vai trò = tài khoản khác


def test_two_people_with_different_names_are_isolated_companies(client):
    ta, a = as_(client, "Công ty A", "shipper")
    tb, b = as_(client, "Công ty B", "shipper")
    assert a["org_id"] != b["org_id"]
    a_ids = {x["id"] for x in lots(client, ta)}
    b_ids = {x["id"] for x in lots(client, tb)}
    assert a_ids and b_ids and a_ids.isdisjoint(b_ids)
    for lid in b_ids:                                                           # đọc/sửa/huỷ lô của bên kia → 404
        assert get(client, ta, f"/v1/shipments/{lid}").status_code == 404
        assert client.delete(f"/v1/shipments/{lid}", headers=auth(ta)).status_code == 404
    other = lots(client, tb)[0]
    assert client.patch(f"/v1/shipments/{other['id']}", json={"version": 1, "weight_kg": 1}, headers=auth(ta)).status_code == 404
    assert all(x["price_vnd"] is None for x in get(client, ta, "/v1/shipments").json() if x["id"] in b_ids)


def test_the_team_names_map_to_the_seeded_demo_accounts(client):
    tn, nguyen = as_(client, "Nguyên", "shipper")
    assert tn == "shipper_a" and len(lots(client, tn)) == 10 and nguyen["org_name"].startswith("Công ty Hàng hóa A")
    assert as_(client, "nguyen", "shipper")[0] == "shipper_a"                   # không dấu / hoa-thường vẫn khớp
    assert as_(client, "Phước", "shipper")[1]["org_id"] == nguyen["org_id"]     # Phước cùng tổ chức A
    assert as_(client, "Minh", "carrier")[0] == "carrier_b" and as_(client, "Khôi", "node_operator")[0] == "node_c"
    assert as_(client, "Phú", "dispatcher")[0] == "dispatch"
    t, me = as_(client, "Nguyên", "carrier")                                    # cùng tên nhưng khác vai trò → người mới
    assert t != "shipper_a" and me["org_id"] != nguyen["org_id"]
    with SessionLocal() as s:
        assert s.execute(select(func.count()).select_from(m.User).where(m.User.is_registered.is_(True))).scalar_one() == 1


# ---------- luồng nhiều bên giữa các tab ----------
def _isolate_to_registered_resources():
    """Chỉ để test: loại xe/slot mẫu của seed để đề xuất chắc chắn dùng tài nguyên của người mới đăng nhập."""
    with SessionLocal() as s:
        reg = accounts.registered_org_ids(s)
        s.execute(update(m.Vehicle).where(m.Vehicle.tenant_id.notin_(reg)).values(status="offline"))
        s.execute(update(m.Slot).where(m.Slot.node_org_id.notin_(reg)).values(remaining=0))
        s.commit()


def test_three_new_people_complete_a_cross_organisation_booking(client):
    th, hoa = as_(client, "Hoa", "shipper")
    tl, lan = as_(client, "Lan", "carrier")
    tc, cuong = as_(client, "Cường", "node_operator")
    _isolate_to_registered_resources()
    lot = next(x for x in lots(client, th) if x["code"] == "LOT-001")
    run = client.post("/v1/match-runs", json={"shipment_id": lot["id"]}, headers=auth(th)).json()
    assert run["status"] == "proposals", run
    prop = run["proposals"][0]
    assert prop["vehicle"]["carrier_org_name"] == lan["org_name"] and prop["slot"]["node_org_name"] == cuong["org_name"]

    def act(token, action):
        v = get(client, token, f"/v1/proposals/{prop['id']}").json()
        return client.post(f"/v1/proposals/{prop['id']}/{action}", json={"version": v["version"]},
                           headers={**auth(token), "Idempotency-Key": str(uuid.uuid4())})
    assert act(th, "hold").status_code == 200
    assert act(th, "accept").status_code == 200 and act(tl, "accept").status_code == 200 and act(tc, "accept").status_code == 200
    done = get(client, th, f"/v1/proposals/{prop['id']}").json()
    assert done["status"] == "confirmed" and all(p["accepted"] for p in done["parties"].values())
    # mỗi bên chỉ thấy phần của mình
    outsider = client.post(f"/v1/proposals/{prop['id']}/accept", json={"version": 1},
                           headers={**auth("shipper_a"), "Idempotency-Key": str(uuid.uuid4())})
    assert outsider.status_code == 404                                          # người ngoài cuộc không thấy đề xuất
    assert get(client, "shipper_a", f"/v1/proposals/{prop['id']}").status_code == 404


def test_vehicle_plates_of_different_carriers_never_collide(client):
    plates = []
    for name in ("Lan", "Mai", "Nam", "Oanh", "Phong"):
        t, _ = as_(client, name, "carrier")
        plates += [v["plate"] for v in get(client, t, "/v1/vehicles").json()]
    assert len(plates) == len(set(plates)) == 20


# ---------- reset / retime ----------
def test_reset_keeps_identities_and_reprovisions_sample_data(client):
    th, hoa = as_(client, "Hoa", "shipper")
    tl, lan = as_(client, "Lan", "carrier")
    body = {"code": "LOT-RIENG", "cargo_type": "dry", "weight_kg": 5000, "volume_m3": 10,
            "origin_location_id": client.get("/v1/locations", headers=auth(th)).json()[0]["id"],
            "dest_location_id": next(l["id"] for l in client.get("/v1/locations", headers=auth(th)).json() if l["kind"] == "icd"),
            "ready_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "pickup_deadline": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            "cutoff_at": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()}
    assert client.post("/v1/shipments", json=body, headers=auth(th)).status_code in (200, 201)
    assert len(lots(client, th)) == 5
    td, _ = as_(client, "Phú", "dispatcher")
    r = client.post("/v1/demo/reset", headers=auth(td))
    assert r.status_code == 200 and r.json()["registered_orgs_reprovisioned"] == 2
    assert get(client, th, "/v1/me").json()["org_id"] == hoa["org_id"]          # tab đang mở không bị văng ra
    assert [x["code"] for x in lots(client, th)] == ["LOT-001", "LOT-002", "LOT-003", "LOT-004"]   # lô tự tạo bị xoá, dữ liệu mẫu được cấp lại
    assert len(get(client, tl, "/v1/vehicles").json()) == 4
    assert len(lots(client, "shipper_a")) == 10                                 # dữ liệu seed chuẩn vẫn nguyên
    with SessionLocal() as s:
        assert s.execute(select(func.count()).select_from(m.Organization).where(m.Organization.is_registered.is_(True))).scalar_one() == 2


def test_retime_does_not_shift_data_created_by_registered_people(client):
    th, _ = as_(client, "Hoa", "shipper")
    before = {x["code"]: x["ready_at"] for x in lots(client, th)}
    seeded_before = {x["code"]: x["ready_at"] for x in lots(client, "shipper_a")}
    with SessionLocal() as s:                                                   # giả lập: seed đã 30 phút trước
        a = s.execute(select(m.AssumptionSet)).scalars().first()
        a.params = {**a.params, "anchor_at": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()}
        s.commit()
    td, _ = as_(client, "Phú", "dispatcher")
    assert client.post("/v1/demo/retime", headers=auth(td)).status_code == 200
    assert {x["code"]: x["ready_at"] for x in lots(client, th)} == before       # dữ liệu của người đăng ký giữ nguyên
    after = {x["code"]: x["ready_at"] for x in lots(client, "shipper_a")}
    assert after != seeded_before                                               # dữ liệu seed vẫn được dịch


# ---------- an toàn ----------
def test_login_is_disabled_outside_the_simulated_demo(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_dev_tokens", False)
    assert login(client, "Hoa", "shipper").status_code == 403
    monkeypatch.setattr(settings, "allow_dev_tokens", True)
    monkeypatch.setattr(settings, "data_mode", "live")
    assert login(client, "Hoa", "shipper").status_code == 403


def test_registration_cap_protects_a_public_deployment(client, monkeypatch):
    monkeypatch.setattr(accounts, "MAX_REGISTERED_USERS", 2)
    assert login(client, "Một", "shipper").status_code == 200 and login(client, "Hai", "shipper").status_code == 200
    r = login(client, "Ba", "shipper")
    assert r.status_code == 429 and r.json()["detail"]["code"] == "REGISTRATION_LIMIT"
    assert login(client, "Một", "shipper").status_code == 200                   # người đã có vẫn đăng nhập được
    assert login(client, "Nguyên", "shipper").status_code == 200                # tài khoản mẫu không bị trần chặn


def test_concurrent_first_logins_of_the_same_name_create_one_account(client):
    out, barrier = [], threading.Barrier(6)

    def go():
        c = TestClient(app, raise_server_exceptions=False)
        barrier.wait()
        out.append(c.post("/v1/auth/login", json={"name": "Đồng Thời", "role": "shipper"}).status_code)
    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out == [200] * 6
    with SessionLocal() as s:
        orgs = s.execute(select(m.Organization).where(m.Organization.name == "Đồng Thời · Chủ hàng")).scalars().all()
        assert len(orgs) == 1
        assert s.execute(select(func.count()).select_from(m.Shipment).where(m.Shipment.tenant_id == orgs[0].id)).scalar_one() == 4
