"""Hard gate → score → xếp hạng (DRAFT 5.1/5.2, điều kiện qua Ngày 2) + các khoảng trống đã sửa sau review."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event as sa_event, select

from app import models as m
from app.db import SessionLocal, engine
from app.matching import gates, score
from tests.conftest import auth
from tests.helpers import match


def _codes(run):
    return {r["plate"]: {x["reason_code"] for x in r["reasons"]} for r in run["rejections"]}


def test_match_ranks_feasible_vehicles_and_explains_rejections(client):
    run = match(client, "dispatch", "LOT-A-001")  # điều phối viên thấy đủ biển số + chi tiết
    assert run["status"] == "proposals" and run["eta_method"] == "rule-based"
    assert run["evaluated_vehicles"] == 10
    plates = [p["vehicle"]["plate"] for p in run["proposals"]]
    assert 1 <= len(plates) <= 3 and set(plates) <= {"51C-100.01", "51C-100.02", "51C-100.03", "51C-100.04"}
    rej = _codes(run)
    assert gates.CAPACITY_EXCEEDED in rej["51C-100.05"]        # thiếu tải
    assert gates.CARGO_INCOMPATIBLE in rej["51C-100.07"]       # sai loại hàng
    assert gates.DATA_STALE in rej["51C-100.08"]               # vị trí quá hạn
    assert gates.PICKUP_WINDOW_MISSED in rej["51C-100.09"]     # trễ giờ lấy hàng
    assert gates.VEHICLE_UNAVAILABLE in rej["51C-100.10"]      # offline


def test_other_orgs_fleet_details_are_redacted_for_the_shipper(client):
    """Governance (DRAFT): chủ hàng không thấy chi tiết đội xe của nhà vận tải khác, chỉ mã lý do + dữ kiện của lô mình."""
    run = match(client, "shipper_a", "LOT-A-001")
    assert run["rejections"] and all("•••" in r["plate"] for r in run["rejections"])
    leaked = {"capacity_kg", "capacity_m3", "vehicle_accepts", "age_minutes", "eta_pickup", "status"}
    for r in run["rejections"]:
        for x in r["reasons"]:
            assert x["detail"].get("redacted") is True and not leaked & set(x["detail"]), x
    codes = {x["reason_code"] for r in run["rejections"] for x in r["reasons"]}
    assert {"CAPACITY_EXCEEDED", "CARGO_INCOMPATIBLE", "DATA_STALE"} <= codes          # lý do vẫn đủ để giải thích
    # nhà vận tải sở hữu xe và điều phối viên thấy đủ
    own = match(client, "carrier_b", "LOT-B-011")
    assert any(not r["plate"].count("•") for r in own["rejections"])
    stored = client.get(f"/v1/proposals/{run['proposals'][0]['id']}", headers=auth("shipper_a")).json()
    assert all("•••" in r["plate"] for r in stored["rejections"])                       # cũng che khi xem lại đề xuất
    full = client.get(f"/v1/proposals/{run['proposals'][0]['id']}", headers=auth("dispatch")).json()
    assert any("capacity_kg" in x["detail"] for r in full["rejections"] for x in r["reasons"])


def test_proposal_list_uses_a_constant_number_of_queries(client):
    for code in ("LOT-A-001", "LOT-A-002", "LOT-A-004", "LOT-A-009"):
        match(client, "shipper_a", code)
    counts = []
    def hook(*a, **k): counts.append(1)
    sa_event.listen(engine, "before_cursor_execute", hook)
    try:
        r = client.get("/v1/proposals", headers=auth("shipper_a"))
    finally:
        sa_event.remove(engine, "before_cursor_execute", hook)
    assert r.status_code == 200 and len(r.json()) >= 8
    assert len(counts) <= 14, f"{len(counts)} queries for {len(r.json())} proposals"


def test_rejected_candidates_are_never_scored(client):
    run = match(client, "shipper_a", "LOT-A-001")
    proposed = {p["vehicle"]["id"] for p in run["proposals"]}
    assert proposed.isdisjoint({r["vehicle_id"] for r in run["rejections"]})
    for p in run["proposals"]:
        assert p["gates"] and all(g["status"] == "PASS" for g in p["gates"])  # chỉ ứng viên đạt mới có điểm


def test_score_is_normalised_ranked_and_versioned(client):
    run = match(client, "shipper_a", "LOT-A-001")
    scores = [p["score"] for p in run["proposals"]]
    assert scores == sorted(scores, reverse=True)
    for p in run["proposals"]:
        c = p["score_components"]
        assert all(0.0 <= c[k] <= 1.0 for k in ("fit", "time_margin", "empty_km_saved"))
        assert abs(sum(c["weights"].values()) - 1.0) < 1e-9
        assert 0.0 <= p["score"] <= 1.0
        assert p["rule_version"] == "rules-v1" and p["assumption_version"] == "assume-v2"
        assert p["model_version"] == "rule-based" and p["eta"]["method"] == "rule-based"
        assert p["estimated_saving_vnd"] is not None  # tiền tách khỏi điểm
        assert "price_vnd" not in p["shipment"] and "customer_name" not in p["shipment"]


def test_no_feasible_option_is_returned_not_forced(client):
    run = match(client, "shipper_a", "LOT-A-008")  # cutoff ICD quá sát: mọi xe đều CUTOFF_RISK
    assert run["status"] == "no_feasible_option" and run["proposals"] == []
    assert any(gates.CUTOFF_RISK in {x["reason_code"] for x in r["reasons"]} for r in run["rejections"])


def test_missing_required_field_means_needs_data(client):
    run = match(client, "shipper_a", "LOT-A-007")  # thiếu trọng lượng/thể tích
    assert run["status"] == "needs_data" and run["proposals"] == []
    assert any(x["reason_code"] == gates.MISSING_FIELD for r in run["needs_data"] for x in r["reasons"])


def test_match_run_is_persisted_as_event_with_versions(client):
    run = match(client, "shipper_a", "LOT-A-001")
    with SessionLocal() as s:
        ev = s.execute(select(m.Event).where(m.Event.event_type == "MATCH_RUN_COMPLETED")).scalars().one()
        assert ev.source_event_id == run["run_id"] and ev.payload["rule_version"] == "rules-v1"
        prop = s.execute(select(m.Proposal)).scalars().first()
        assert prop.input_snapshot["run_id"] == run["run_id"] and prop.candidate_rejections


def test_cannot_match_other_tenants_or_invisible_lots(client):
    from tests.helpers import lot_id
    a_lot = lot_id(client, "shipper_a", "LOT-A-001")
    assert client.post("/v1/match-runs", json={"shipment_id": a_lot}, headers=auth("carrier_b")).status_code == 404
    assert client.post("/v1/match-runs", json={"shipment_id": a_lot}, headers=auth("node_c")).status_code == 404


def test_proposals_are_visible_only_to_parties_and_hide_price(client):
    run = match(client, "shipper_a", "LOT-A-001")
    pid = run["proposals"][0]["id"]
    for user in ("shipper_a", "carrier_b", "node_c", "dispatch"):
        r = client.get(f"/v1/proposals/{pid}", headers=auth(user))
        assert r.status_code == 200 and "price_vnd" not in r.json()["shipment"]


# ---- các khoảng trống gate đã sửa sau review ----
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
PARAMS = {"stale_shipment_minutes": 60}


def test_stale_shipment_data_is_rejected():
    ship = SimpleNamespace(data_updated_at=NOW - timedelta(minutes=61))
    r = gates.gate_shipment_fresh(ship, NOW, PARAMS)
    assert (r.status, r.reason_code) == ("FAIL", gates.DATA_STALE)
    assert gates.gate_shipment_fresh(SimpleNamespace(data_updated_at=NOW - timedelta(minutes=59)), NOW, PARAMS).status == "PASS"
    assert gates.gate_shipment_fresh(SimpleNamespace(data_updated_at=None), NOW, PARAMS).status == "UNKNOWN"


def test_slot_at_wrong_location_is_rejected():
    ship = SimpleNamespace(dest_location_id="icd", ready_at=NOW, pickup_deadline=NOW + timedelta(hours=3),
                           cutoff_at=NOW + timedelta(hours=9))
    window = SimpleNamespace(free_from=NOW, free_to=NOW + timedelta(hours=9))
    params = {"deadhead_minutes": 25, "transit_minutes": 90, "handling_minutes": 20}
    good = SimpleNamespace(id="s", location_id="icd", remaining=2, source="mock", end_at=NOW + timedelta(hours=8))
    assert gates.gate_slot(good, ship, window, NOW, params).status == "PASS"
    bad = SimpleNamespace(id="s", location_id="elsewhere", remaining=2, source="mock", end_at=NOW + timedelta(hours=8))
    r = gates.gate_slot(bad, ship, window, NOW, params)
    assert (r.status, r.reason_code) == ("FAIL", gates.SLOT_LOCATION_MISMATCH)
    late = SimpleNamespace(id="s", location_id="icd", remaining=2, source="mock", end_at=NOW + timedelta(minutes=30))
    assert gates.gate_slot(late, ship, window, NOW, params).reason_code == gates.SLOT_WINDOW_MISSED


def test_score_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        score.check_weights({"fit": 0.5, "time_margin": 0.3, "empty_km_saved": 0.3})


def test_meta_without_active_assumption_is_503_not_500(client):
    with SessionLocal() as s:
        s.execute(m.AssumptionSet.__table__.update().values(is_active=False))
        s.commit()
    assert client.get("/v1/meta", headers=auth("shipper_a")).status_code == 503


def test_dispatcher_list_has_no_n_plus_one(client):
    count = [0]

    def hook(*a, **k):
        count[0] += 1
    sa_event.listen(engine, "before_cursor_execute", hook)
    try:
        r = client.get("/v1/shipments", headers=auth("dispatch"))
    finally:
        sa_event.remove(engine, "before_cursor_execute", hook)
    assert r.status_code == 200 and len(r.json()) == 20
    assert count[0] <= 4, f"{count[0]} queries for one list call"


def test_dev_tokens_refuse_to_start_outside_mock(monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app
    monkeypatch.setattr(settings, "data_mode", "live")
    monkeypatch.setattr(settings, "worker_inline", False)
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass


def test_proposals_are_spread_across_icds_so_every_icd_gets_a_request(client):
    """Hai ICD cùng có slot đạt: trước đây ICD có slot sớm nhất nhận hết đề xuất, ICD kia không bao giờ thấy yêu cầu nào."""
    from sqlalchemy import select
    from app import models as m
    from app.db import SessionLocal
    with SessionLocal() as s:
        org = m.Organization(name="ICD Khác (test)", org_type="node")
        s.add(org)
        s.flush()
        for sl in s.execute(select(m.Slot)).scalars().all():
            s.add(m.Slot(node_org_id=org.id, location_id=sl.location_id, start_at=sl.start_at + timedelta(minutes=1),
                         end_at=sl.end_at + timedelta(minutes=1), capacity=sl.capacity, remaining=sl.remaining, source="mock"))
        s.commit()
    props = match(client, "shipper_a", "LOT-A-001")["proposals"]
    assert len(props) >= 2
    assert {p["slot"]["node_org_name"] for p in props} == {"ICD Cảng C (Node)", "ICD Khác (test)"}
    assert all(p["gates"] and all(g["status"] == "PASS" for g in p["gates"]) for p in props)   # slot đổi vẫn qua hard gate
