"""Điều kiện qua Ngày 1 (DRAFT bảng 3): tạo/đọc lô OK; tổ chức A KHÔNG đọc được lô riêng của B — qua API trực tiếp."""
from datetime import datetime, timedelta, timezone

from tests.conftest import auth


def _ids(resp):
    return {s["id"] for s in resp.json()}


def test_requires_token(client):
    assert client.get("/v1/shipments").status_code == 401
    assert client.get("/v1/shipments", headers={"Authorization": "Bearer dev:nobody"}).status_code == 401


def test_each_org_lists_only_own_shipments(client):
    a = client.get("/v1/shipments", headers=auth("shipper_a"))
    b = client.get("/v1/shipments", headers=auth("carrier_b"))
    assert a.status_code == b.status_code == 200
    assert len(a.json()) == 10 and len(b.json()) == 10
    assert _ids(a).isdisjoint(_ids(b))
    assert all(s["code"].startswith("LOT-A") for s in a.json())
    assert all(s["code"].startswith("LOT-B") for s in b.json())


def test_cross_tenant_read_by_id_is_404(client):
    b_lot = client.get("/v1/shipments", headers=auth("carrier_b")).json()[0]["id"]
    a_lot = client.get("/v1/shipments", headers=auth("shipper_a")).json()[0]["id"]
    assert client.get(f"/v1/shipments/{b_lot}", headers=auth("shipper_a")).status_code == 404
    assert client.get(f"/v1/shipments/{a_lot}", headers=auth("carrier_b")).status_code == 404
    # node chưa là participant của lô nào → không thấy
    assert client.get(f"/v1/shipments/{a_lot}", headers=auth("node_c")).status_code == 404
    assert client.get("/v1/shipments", headers=auth("node_c")).json() == []


def test_owner_sees_price_dispatcher_does_not(client):
    own = client.get("/v1/shipments", headers=auth("shipper_a")).json()
    assert any(s["price_vnd"] is not None and s["customer_name"] for s in own)
    disp = client.get("/v1/shipments", headers=auth("dispatch")).json()
    assert len(disp) == 20  # điều phối viên thấy metadata mọi lô
    assert all(s["price_vnd"] is None and s["customer_name"] is None for s in disp)


def test_vehicles_scoped_to_carrier(client):
    assert len(client.get("/v1/vehicles", headers=auth("carrier_b")).json()) == 10
    assert client.get("/v1/vehicles", headers=auth("shipper_a")).json() == []


def test_create_and_read_shipment(client):
    locs = {l["name"]: l["id"] for l in client.get("/v1/locations", headers=auth("shipper_a")).json()}
    kcn = next(v for k, v in locs.items() if k.startswith("KCN Sóng Thần"))
    icd = next(v for k, v in locs.items() if k.startswith("ICD"))
    now = datetime.now(timezone.utc)
    body = {"code": "LOT-A-NEW", "cargo_type": "dry", "weight_kg": 9000, "volume_m3": 22,
            "origin_location_id": kcn, "dest_location_id": icd,
            "ready_at": (now + timedelta(hours=1)).isoformat(),
            "pickup_deadline": (now + timedelta(hours=4)).isoformat(),
            "cutoff_at": (now + timedelta(hours=12)).isoformat(), "price_vnd": 1000000}
    r = client.post("/v1/shipments", json=body, headers=auth("shipper_a"))
    assert r.status_code == 201
    new_id = r.json()["id"]
    assert client.get(f"/v1/shipments/{new_id}", headers=auth("shipper_a")).status_code == 200
    assert client.get(f"/v1/shipments/{new_id}", headers=auth("carrier_b")).status_code == 404


def test_incomplete_request_creates_nothing(client):
    r = client.post("/v1/shipments", json={"code": "LOT-X", "cargo_type": "dry"}, headers=auth("shipper_a"))
    assert r.status_code == 422
    codes = [s["code"] for s in client.get("/v1/shipments", headers=auth("shipper_a")).json()]
    assert "LOT-X" not in codes


def test_node_and_dispatcher_cannot_create(client):
    assert client.post("/v1/shipments", json={}, headers=auth("node_c")).status_code in (403, 422)
    body = {"code": "LOT-N", "cargo_type": "dry", "weight_kg": 1, "volume_m3": 1,
            "origin_location_id": "00000000-0000-0000-0000-000000000000",
            "dest_location_id": "00000000-0000-0000-0000-000000000000",
            "ready_at": "2030-01-01T00:00:00Z", "pickup_deadline": "2030-01-01T01:00:00Z",
            "cutoff_at": "2030-01-01T05:00:00Z"}
    assert client.post("/v1/shipments", json=body, headers=auth("node_c")).status_code == 403
    assert client.post("/v1/shipments", json=body, headers=auth("dispatch")).status_code == 403


def test_second_member_of_same_org_shares_lots_but_not_other_orgs(client):
    nguyen = client.get("/v1/shipments", headers=auth("shipper_a")).json()
    phuoc = client.get("/v1/shipments", headers=auth("shipper_a2")).json()
    assert _ids_from(nguyen) == _ids_from(phuoc) and len(phuoc) == 10          # cùng tổ chức A: cùng lô
    assert all(s["customer_name"] for s in phuoc)                               # cùng tổ chức: thấy cả tên khách hàng
    me = client.get("/v1/me", headers=auth("shipper_a2")).json()
    assert me["role"] == "shipper" and me["user_name"].startswith("Phước")
    b_lot = client.get("/v1/shipments", headers=auth("carrier_b")).json()[0]["id"]
    assert client.get(f"/v1/shipments/{b_lot}", headers=auth("shipper_a2")).status_code == 404


def _ids_from(rows):
    return {r["id"] for r in rows}
