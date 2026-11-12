"""Nguồn cung slot MÔ PHỎNG của ICD tự được duy trì (không còn 'chết' theo thời gian) mà KHÔNG nới hard gate."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app import models as m
from app import nodes
from app.db import SessionLocal
from tests.conftest import auth
from tests.helpers import match

UTC = timezone.utc


def expire_all_slots(org_id=None):
    """Đưa mọi slot (hoặc của một ICD) về quá khứ — đúng tình trạng ảnh chụp: SLOT_WINDOW_MISSED hàng loạt."""
    past = datetime.now(UTC) - timedelta(days=2)
    with SessionLocal() as s:
        q = select(m.Slot) if org_id is None else select(m.Slot).where(m.Slot.node_org_id == org_id)
        for sl in s.execute(q).scalars():
            sl.start_at, sl.end_at = past, past + timedelta(minutes=30)
            past += timedelta(minutes=31)
        s.commit()


def org_id_of(name_part):
    with SessionLocal() as s:
        return s.execute(select(m.Organization.id).where(m.Organization.name.like(f"%{name_part}%"))).scalar_one()


def slots_of(org_id):
    with SessionLocal() as s:
        return list(s.execute(select(m.Slot).where(m.Slot.node_org_id == org_id).order_by(m.Slot.start_at)).scalars())


# ---------------------------------------------------------------- sinh slot
def test_expired_calendar_is_extended_with_contiguous_future_simulated_slots(client):
    org = org_id_of("ICD Cảng C")
    expire_all_slots()
    old = {s.id: (s.start_at, s.end_at, s.remaining) for s in slots_of(org)}
    now = datetime.now(UTC)
    with SessionLocal() as s:
        out = nodes.refresh_slots(s, org, now)
        s.commit()
    assert out["reason"] == "EXTENDED" and out["created"] >= 15
    new = [x for x in slots_of(org) if x.id not in old]
    assert len(new) == out["created"]
    assert all(x.source == "mock" and x.is_simulated and 2 <= x.capacity <= 4 and x.remaining == x.capacity for x in new)
    assert new[0].start_at >= now + timedelta(minutes=30) and new[-1].end_at <= now + timedelta(hours=10, minutes=1)
    for a, b in zip(new, new[1:]):
        assert b.start_at == a.end_at and (a.end_at - a.start_at) == timedelta(minutes=30)          # liền nhau, không chồng lấn
    assert {s.id: (s.start_at, s.end_at, s.remaining) for s in slots_of(org) if s.id in old} == old  # slot cũ (kể cả đã qua) không bị đụng


def test_refresh_is_idempotent_and_leaves_a_fresh_calendar_alone(client):
    org = org_id_of("ICD Cảng C")
    with SessionLocal() as s:
        n0 = s.execute(select(func.count()).select_from(m.Slot)).scalar_one()
        out = nodes.refresh_slots(s, org, datetime.now(UTC))                                       # seed còn ~12 giờ phía trước → không sinh
        s.commit()
        assert out["created"] == 0 and out["reason"] == "COVERED"
        assert s.execute(select(func.count()).select_from(m.Slot)).scalar_one() == n0
    expire_all_slots(org)
    with SessionLocal() as s:
        a = nodes.refresh_slots(s, org, datetime.now(UTC))
        s.commit()
        b = nodes.refresh_slots(s, org, datetime.now(UTC))
        s.commit()
    assert a["created"] > 0 and b["created"] == 0


def test_concurrent_refreshes_never_create_duplicate_or_overlapping_slots(client):
    org = org_id_of("ICD Cảng C")
    expire_all_slots(org)

    def go(_):
        with SessionLocal() as s:
            out = nodes.refresh_slots(s, org, datetime.now(UTC))
            s.commit()
            return out["created"]
    with ThreadPoolExecutor(6) as ex:
        created = list(ex.map(go, range(6)))
    future = [x for x in slots_of(org) if x.start_at > datetime.now(UTC)]
    assert sum(created) == len(future)                                                              # chỉ MỘT lượt thực sự sinh
    assert all(b.start_at >= a.end_at for a, b in zip(future, future[1:]))


def test_real_partner_slots_and_empty_icds_are_never_given_invented_supply(client):
    org = org_id_of("ICD Cảng C")
    expire_all_slots(org)
    with SessionLocal() as s:
        sl = s.execute(select(m.Slot).where(m.Slot.node_org_id == org)).scalars().first()
        sl.source, sl.is_simulated = "partner_api", False
        s.commit()
        assert nodes.refresh_slots(s, org, datetime.now(UTC)) == {"created": 0, "reason": "NOT_SIMULATED"}
        empty = m.Organization(name="ICD rỗng (test)", org_type="node")
        s.add(empty)
        s.flush()
        assert nodes.refresh_slots(s, empty.id, datetime.now(UTC)) == {"created": 0, "reason": "NO_SLOTS"}


# ---------------------------------------------------------------- các điểm kích hoạt
def test_matching_works_again_after_every_slot_has_expired(client):
    expire_all_slots()
    res = match(client, "shipper_a", "LOT-A-001")
    assert res["status"] == "proposals" and res["proposals"]                                       # trước đây: không có phương án khả thi
    now = datetime.now(UTC)
    assert all(datetime.fromisoformat(p["slot"]["start_at"]) > now for p in res["proposals"])


def test_generated_slots_still_obey_the_hard_gate_cutoff(client):
    with SessionLocal() as s:
        lot = s.execute(select(m.Shipment).where(m.Shipment.code == "LOT-A-001")).scalar_one()
        lot.cutoff_at = datetime.now(UTC) + timedelta(hours=3)
        s.commit()
        cutoff = lot.cutoff_at
    expire_all_slots()
    res = match(client, "shipper_a", "LOT-A-001")
    assert all(datetime.fromisoformat(p["slot"]["start_at"]) <= cutoff for p in res["proposals"])  # slot sau cut-off vẫn bị gate loại
    codes = {x["reason_code"] for r in res["rejections"] for x in r["reasons"]}
    assert res["proposals"] or codes                                                               # không có phương án thì phải nêu lý do, không ép ghép


def test_matching_on_a_fresh_seed_creates_no_slots(client):
    with SessionLocal() as s:
        n0 = s.execute(select(func.count()).select_from(m.Slot)).scalar_one()
    match(client, "shipper_a", "LOT-A-001")
    with SessionLocal() as s:
        assert s.execute(select(func.count()).select_from(m.Slot)).scalar_one() == n0              # dữ liệu tươi không bị đụng (kịch bản/test cũ ổn định)


def test_icd_login_extends_its_own_calendar_only(client):
    tok = client.post("/v1/auth/login", json={"name": "ICD Moi", "role": "node_operator"}).json()["token"]
    org = org_id_of("ICD Moi")
    c_before = len(slots_of(org_id_of("ICD Cảng C")))
    expire_all_slots(org)
    assert [x for x in slots_of(org) if x.start_at > datetime.now(UTC)] == []
    assert client.post("/v1/auth/login", json={"name": "ICD Moi", "role": "node_operator"}).status_code == 200
    assert len([x for x in slots_of(org) if x.start_at > datetime.now(UTC)]) >= 15
    assert len(slots_of(org_id_of("ICD Cảng C"))) == c_before                                       # ICD khác không bị sinh hộ
    assert tok


def test_refresh_endpoint_is_for_icd_operators_only(client):
    for user in ("shipper_a", "carrier_b", "dispatch"):
        assert client.post("/v1/slots/refresh", headers=auth(user)).status_code == 403
    expire_all_slots()
    r = client.post("/v1/slots/refresh", headers=auth("node_c"))
    assert r.status_code == 200 and r.json()["created"] > 0 and r.json()["is_simulated"] is True
