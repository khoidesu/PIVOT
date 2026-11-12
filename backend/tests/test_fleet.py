"""Đội xe nhà vận tải: tự làm tươi vị trí/khung rảnh khi đăng nhập (đường sự kiện thật) + bãi đậu / khoảng cách minh bạch."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import event as sa_event, select

from app import fleet
from app import models as m
from app.auth import actor_for_key
from app.db import SessionLocal, engine
from app.matching import score
from tests.conftest import auth
from tests.helpers import act, match, run_worker

UTC = timezone.utc


def vehicles(client, user, **params):
    r = client.get("/v1/vehicles", params=params, headers=auth(user))
    assert r.status_code == 200, r.text
    return {v["plate"]: v for v in r.json()}


def age_all(minutes=30):
    with SessionLocal() as s:
        for v in s.execute(select(m.Vehicle)).scalars():
            v.position_updated_at = datetime.now(UTC) - timedelta(minutes=minutes)
        s.commit()


def loc(client, kind=None, name=None):
    rows = client.get("/v1/locations", headers=auth("shipper_a")).json()
    return next(x for x in rows if (kind is None or x["kind"] == kind) and (name is None or name in x["name"]))


# ---------------------------------------------------------------- 1. làm tươi khi đăng nhập
def test_refresh_makes_available_vehicles_fresh_and_leaves_offline_and_busy_alone(client):
    age_all(30)
    before = vehicles(client, "carrier_b")
    assert all(v["position_age_seconds"] > 5 * 60 for v in before.values())                 # đang quá hạn (DATA_STALE)
    r = client.post("/v1/vehicles/refresh-fleet", headers=auth("carrier_b"))
    assert r.status_code == 200 and r.json()["is_simulated"] is True
    run_worker(client)
    after = vehicles(client, "carrier_b")
    offline = [p for p, v in before.items() if v["status"] == "offline"]
    assert offline and r.json()["skipped"]["offline"] == len(offline)
    for plate, v in after.items():
        if plate in offline:
            assert v["status"] == "offline" and v["position_age_seconds"] > 5 * 60            # không tự bật lại xe offline
        else:
            assert v["position_age_seconds"] < 60, plate
    assert r.json()["updated"] == len(after) - len(offline)


def test_refresh_is_idempotent_within_the_same_minute(client):
    with SessionLocal() as s:
        actor = actor_for_key(s, "carrier_b")
        now = datetime.now(UTC)
        first = fleet.refresh_fleet(s, actor, now)
        s.commit()
        second = fleet.refresh_fleet(s, actor, now)
        s.commit()
        assert first["updated"] > 0 and second["updated"] == 0 and second["already_fresh"] == first["updated"]
        n = s.execute(select(m.Event).where(m.Event.source_system == "sim-login", m.Event.event_type == "VEHICLE_POSITION")).scalars().all()
        assert len(n) == first["updated"]                                                    # gửi lặp không nhân đôi sự kiện


def test_only_the_carrier_can_refresh_and_never_other_orgs_vehicles(client):
    for user in ("shipper_a", "node_c", "dispatch"):
        assert client.post("/v1/vehicles/refresh-fleet", headers=auth(user)).status_code == 403
    tok = client.post("/v1/auth/login", json={"name": "Hang Khac", "role": "carrier"}).json()["token"]
    age_all(30)
    client.post("/v1/vehicles/refresh-fleet", headers=auth(tok))
    run_worker(client)
    assert all(v["position_age_seconds"] > 5 * 60 for v in vehicles(client, "carrier_b").values())   # xe tổ chức B không bị đụng tới


def test_expired_availability_window_is_extended_but_a_future_one_is_not(client):
    now = datetime.now(UTC)
    with SessionLocal() as s:
        ws = s.execute(select(m.AvailabilityWindow).join(m.Vehicle, m.Vehicle.id == m.AvailabilityWindow.vehicle_id)
                       .where(m.Vehicle.plate.in_(("51C-100.01", "51C-100.02")))).scalars().all()
        by_plate = {s.get(m.Vehicle, w.vehicle_id).plate: w for w in ws}
        by_plate["51C-100.01"].free_from, by_plate["51C-100.01"].free_to = now - timedelta(hours=3), now - timedelta(hours=1)   # đã hết hạn
        by_plate["51C-100.02"].free_from, by_plate["51C-100.02"].free_to = now + timedelta(hours=3), now + timedelta(hours=4)   # rảnh trong tương lai
        s.commit()
    client.post("/v1/vehicles/refresh-fleet", headers=auth("carrier_b"))
    run_worker(client)
    v = vehicles(client, "carrier_b")
    assert datetime.fromisoformat(v["51C-100.01"]["free_to"]) > now + timedelta(hours=4)    # gia hạn
    assert datetime.fromisoformat(v["51C-100.02"]["free_from"]) > now + timedelta(hours=2)  # không đổi giờ rảnh trong tương lai


def test_login_refreshes_the_carriers_fleet_but_not_a_shippers_login(client):
    tok = client.post("/v1/auth/login", json={"name": "Van Tai Moi", "role": "carrier"}).json()["token"]
    run_worker(client)
    with SessionLocal() as s:                                                                        # giả lập đã sang phút khác (khoá chống trùng theo phút)
        for e in s.execute(select(m.Event).where(m.Event.source_system == "sim-login")).scalars():
            s.delete(e)
        s.commit()
    age_all(30)
    r = client.post("/v1/auth/login", json={"name": "Van Tai Moi", "role": "carrier"})            # đăng nhập lại → làm tươi
    assert r.status_code == 200
    run_worker(client)
    mine = vehicles(client, tok)
    assert len(mine) == 4 and all(v["position_age_seconds"] < 60 for v in mine.values())
    with SessionLocal() as s:
        assert s.execute(select(m.Event).where(m.Event.source_system == "sim-login")).scalars().first() is not None
    client.post("/v1/auth/login", json={"name": "Chu Hang Moi", "role": "shipper"})
    with SessionLocal() as s:
        orgs = {e.tenant_id for e in s.execute(select(m.Event).where(m.Event.source_system == "sim-login")).scalars()}
        assert len(orgs) == 1                                                                     # chỉ tổ chức vận tải sinh sự kiện


def test_refresh_does_not_loosen_the_stale_rule_for_vehicles_nobody_refreshed(client):
    age_all(30)
    run_worker(client)
    res = match(client, "shipper_a", "LOT-A-001")
    stale = [r for r in res["rejections"] if any(x["reason_code"] == "DATA_STALE" for x in r["reasons"])]
    assert stale                                                                                   # chưa ai làm tươi → vẫn bị loại DATA_STALE


# ---------------------------------------------------------------- 2. bãi đậu + khoảng cách
def test_vehicle_list_shows_yard_window_age_and_state(client):
    v = vehicles(client, "carrier_b")
    one = v["51C-100.01"]
    assert one["yard"]["name"].startswith("Depot") and one["availability"]["state"] in ("empty", "free_later", "window_expired")
    assert v["51C-100.10"]["availability"] == {"state": "offline", "reason": "VEHICLE_OFFLINE"}
    assert one["position_age_seconds"] is not None and one["free_from"] and one["free_to"]


def test_held_vehicle_is_reported_as_reserved_with_a_reason(client):
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    assert act(client, "shipper_a", prop, "hold").status_code == 200
    v = vehicles(client, "carrier_b")[prop["vehicle"]["plate"]]
    assert v["availability"] == {"state": "reserved", "reason": "HELD_OR_COMMITTED"}


def test_distance_to_target_matches_the_match_score_formula_and_is_labelled_an_estimate(client):
    target = loc(client, kind="industrial_zone", name="Sóng Thần")
    one = vehicles(client, "carrier_b", to_location_id=target["id"])["51C-100.01"]
    expected = round(score.haversine_km(one["yard"]["lat"], one["yard"]["lng"], target["lat"], target["lng"]) * 1.3, 1)
    assert one["distance_to_target_km"] == expected and one["distance_method"] == "estimate"
    assert one["deadhead_eta"]["minutes"] == round(expected / 35 * 60) and one["deadhead_eta"]["p50"] < one["deadhead_eta"]["p90"]
    assert vehicles(client, "carrier_b")["51C-100.01"]["distance_to_target_km"] is None          # không hỏi thì không tính
    assert client.get("/v1/vehicles", params={"to_location_id": "00000000-0000-0000-0000-000000000000"}, headers=auth("carrier_b")).status_code == 422


def test_registered_carriers_vehicles_are_spread_over_several_yards(client):
    tok = client.post("/v1/auth/login", json={"name": "Rai Bai", "role": "carrier"}).json()["token"]
    mine = vehicles(client, tok, to_location_id=loc(client, kind="industrial_zone", name="Sóng Thần")["id"])
    yards = {v["yard"]["name"] for v in mine.values()}
    assert len(yards) >= 3 and all("(mô phỏng)" in y for y in yards)                              # nhãn mô phỏng trong tên bãi
    assert len({v["distance_to_target_km"] for v in mine.values()}) >= 3                           # khoảng cách khác nhau theo bãi


def test_proposal_and_owner_rejections_carry_the_yard_but_other_orgs_never_see_it(client):
    res = match(client, "shipper_a", "LOT-A-001")
    assert all(p["vehicle"]["yard"] for p in res["proposals"])
    for r in res["rejections"] + res["needs_data"]:                                               # chủ lô A KHÔNG phải chủ xe (B) → bản che
        assert "yard" not in r and "yard_km" not in r
    sid = next(x["id"] for x in client.get("/v1/shipments", headers=auth("shipper_a")).json() if x["code"] == "LOT-A-001")
    dispatch = client.post("/v1/match-runs", json={"shipment_id": sid}, headers=auth("dispatch"))
    if dispatch.status_code == 200:                                                               # điều phối viên thấy bản đầy đủ
        full = dispatch.json()["rejections"] + dispatch.json()["needs_data"]
        assert full and all(r.get("yard") for r in full if r["vehicle_id"])


def test_vehicle_list_does_not_scale_queries_with_the_number_of_vehicles(client):
    counts = []

    def hook(conn, cursor, statement, params, context, executemany):
        counts.append(statement)
    sa_event.listen(engine, "before_cursor_execute", hook)
    try:
        client.get("/v1/vehicles", headers=auth("dispatch"))                                      # 10 xe
        small = len(counts)
        counts.clear()
        for i in range(30):
            client.post("/v1/auth/login", json={"name": f"Hang {i:02d}", "role": "carrier"})        # +120 xe
        counts.clear()
        r = client.get("/v1/vehicles", headers=auth("dispatch"))
        assert len(r.json()) >= 100
        assert len(counts) <= small + 2                                                           # số truy vấn không tăng theo số xe (không N+1)
    finally:
        sa_event.remove(engine, "before_cursor_execute", hook)
