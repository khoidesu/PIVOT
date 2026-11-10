"""Sổ lợi ích, timeline, replay, xử lý ngoại lệ (DRAFT 11.1, Ngày 4)."""
import uuid

from sqlalchemy import func, select, update

from app import models as m
from app.db import SessionLocal
from tests.conftest import auth
from tests.helpers import act, confirm_all, get, match, post_event, run_worker


def _completed(client, actual=None, code="LOT-A-001"):
    prop = match(client, "shipper_a", code)["proposals"][0]
    confirm_all(client, prop)
    run_worker(client)
    post_event(client, "carrier_b", prop["id"], "TRIP_STARTED")
    run_worker(client)
    post_event(client, "carrier_b", prop["id"], "TRIP_COMPLETED", {"actual_empty_km": actual} if actual is not None else {})
    run_worker(client)
    return prop


def _ledger(client, user="shipper_a"):
    return client.get("/v1/benefits", headers=auth(user)).json()


def test_estimated_vs_measured_are_kept_apart(client):
    _completed(client)                       # không có số đo → estimated
    est = _ledger(client)["items"]
    assert len(est) == 1 and est[0]["status"] == "estimated"
    assert est[0]["net_vnd"] == round((est[0]["quantity_before"] - est[0]["quantity_after"]) * est[0]["unit_rate"])
    p2 = _completed(client, actual=10.0, code="LOT-A-002")  # có số đo → measured
    items = _ledger(client)["items"]
    assert {i["status"] for i in items} == {"estimated", "measured"}
    totals = _ledger(client)["totals"]
    assert totals["estimated"]["count"] == 1 and totals["measured"]["count"] == 1 and totals["verified"]["count"] == 0
    assert any(i["proposal_id"] == p2["id"] for i in items)


def test_only_measured_can_be_verified_by_a_party(client):
    _completed(client)
    est = _ledger(client)["items"][0]
    r = client.post(f"/v1/benefits/{est['id']}/verify", headers=auth("shipper_a"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_MEASURED"   # ước tính không được xác minh
    _completed(client, actual=12.5, code="LOT-A-002")
    measured = next(i for i in _ledger(client)["items"] if i["status"] == "measured")
    assert measured["can_verify"] is True
    carrier_view = next(i for i in _ledger(client, "carrier_b")["items"] if i["id"] == measured["id"])
    assert carrier_view["can_verify"] is False                       # nhà vận tải không thấy nút xác minh
    assert client.post(f"/v1/benefits/{measured['id']}/verify", headers=auth("dispatch")).status_code == 403
    assert client.post(f"/v1/benefits/{measured['id']}/verify", headers=auth("node_c")).status_code in (403, 404)
    # bên báo số đo (nhà vận tải) KHÔNG được tự xác minh; chỉ đối tác độc lập (chủ hàng) xác minh
    self_v = client.post(f"/v1/benefits/{measured['id']}/verify", headers=auth("carrier_b"))
    assert self_v.status_code == 403 and self_v.json()["detail"]["code"] == "NOT_INDEPENDENT"
    ok = client.post(f"/v1/benefits/{measured['id']}/verify", headers=auth("shipper_a"))
    assert ok.status_code == 200 and ok.json()["status"] == "verified" and "Nguyên" in ok.json()["verifier"]
    assert client.post(f"/v1/benefits/{measured['id']}/verify", headers=auth("shipper_a")).json()["status"] == "verified"  # idempotent
    assert _ledger(client)["totals"]["verified"]["count"] == 1


def test_trip_completed_resent_does_not_double_count(client):
    prop = _completed(client, actual=9.0)
    post_event(client, "carrier_b", prop["id"], "TRIP_COMPLETED", {"actual_empty_km": 9.0})  # tin gửi lại, id khác
    run_worker(client)
    with SessionLocal() as s:
        assert s.execute(select(func.count()).select_from(m.BenefitLedger)).scalar_one() == 1


def test_baseline_is_fixed_before_the_decision(client):
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    with SessionLocal() as s:  # đổi giả định SAU khi ghép: baseline đã chốt không được đổi theo
        a = s.execute(select(m.AssumptionSet)).scalars().one()
        a.params = {**a.params, "empty_km_baseline": 999, "cost_per_km_vnd": 1}
        s.commit()
    confirm_all(client, prop)
    run_worker(client)
    post_event(client, "carrier_b", prop["id"], "TRIP_STARTED"); run_worker(client)
    post_event(client, "carrier_b", prop["id"], "TRIP_COMPLETED", {"actual_empty_km": 5}); run_worker(client)
    row = _ledger(client)["items"][0]
    assert row["quantity_before"] == 38 and row["unit_rate"] == 14000
    detail = client.get(f"/v1/benefits/{row['id']}", headers=auth("shipper_a")).json()
    assert detail["baseline"]["empty_km"] == 38 and detail["evidence"][0]["event_type"] == "TRIP_COMPLETED"
    assert detail["formula"] == {"before": 38.0, "after": 5.0, "rate": 14000.0}


def test_benefit_visibility_follows_the_trip_parties(client):
    _completed(client, actual=8.0)
    assert len(_ledger(client, "shipper_a")["items"]) == 1
    assert len(_ledger(client, "carrier_b")["items"]) == 1
    assert len(_ledger(client, "shipper_a2")["items"]) == 1       # cùng tổ chức chủ hàng
    assert _ledger(client, "node_c")["items"] == []                # node không thấy tiền
    bid = _ledger(client)["items"][0]["id"]
    assert client.get(f"/v1/benefits/{bid}", headers=auth("node_c")).status_code == 404


def test_replay_reproduces_the_stored_decision(client):
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    r = client.get(f"/v1/proposals/{prop['id']}/replay", headers=auth("shipper_a")).json()
    assert r["reproducible"] is True and r["stored_score"] == r["recomputed_score"] == prop["score"]
    assert r["weights_sum"] == 1.0 and r["all_gates_pass"] and r["rule_version"] == "rules-v1"
    assert r["baseline"]["empty_km"] == 38 and "gates" in r["snapshot_keys"]
    with SessionLocal() as s:  # sửa điểm đã lưu → replay phát hiện không tái lập được
        s.execute(update(m.Proposal).where(m.Proposal.id == uuid.UUID(prop["id"])).values(score=0.123))
        s.commit()
    assert client.get(f"/v1/proposals/{prop['id']}/replay", headers=auth("shipper_a")).json()["reproducible"] is False


def test_timeline_is_ordered_attributed_and_flags_late_events(client):
    prop = _completed(client, actual=7.0)
    post_event(client, "carrier_b", prop["id"], "TRIP_STARTED")   # tin muộn
    run_worker(client)
    tl = client.get(f"/v1/proposals/{prop['id']}/timeline", headers=auth("carrier_b")).json()
    assert tl["status"] == "completed"
    ats = [i["at"] for i in tl["items"]]
    assert ats == sorted(ats)
    codes = [i["code"] for i in tl["items"]]
    assert codes[0] == "MATCH_RUN_COMPLETED" and "hold" in codes and codes.count("accept") == 3 and "TRIP_COMPLETED" in codes
    assert any(i["kind"] == "decision" and "Nguyên" in i["actor"] for i in tl["items"])   # có actor
    assert any(i["code"] == "TRIP_STARTED" and i["quality"] == "late" for i in tl["items"])  # tin muộn được đánh dấu
    assert all(i["latency_s"] is not None for i in tl["items"] if i["kind"] == "event")
    assert client.get(f"/v1/proposals/{prop['id']}/timeline", headers=auth("node_c")).status_code == 200  # node là bên liên quan


def test_exception_resolution_is_a_human_decision_and_never_edits_the_trip(client):
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    confirm_all(client, prop); run_worker(client)
    post_event(client, "carrier_b", prop["id"], "TRIP_STARTED"); run_worker(client)
    post_event(client, "carrier_b", prop["id"], "ETA_UPDATED", {"delay_minutes": 30}); run_worker(client)
    ex = client.get("/v1/exceptions", headers=auth("shipper_a")).json()[0]
    before = get(client, "shipper_a", prop["id"])
    assert client.post(f"/v1/exceptions/{ex['id']}/resolve", json={"resolution": "accept_delay"}, headers=auth("dispatch")).status_code == 403
    assert client.post(f"/v1/exceptions/{ex['id']}/resolve", json={"resolution": "accept_delay"}, headers=auth("node_c")).status_code == 403
    assert client.post(f"/v1/exceptions/{ex['id']}/resolve", json={"resolution": "teleport"}, headers=auth("shipper_a")).status_code == 422
    ok = client.post(f"/v1/exceptions/{ex['id']}/resolve", json={"resolution": "request_replan", "note": "cần phương án khác"}, headers=auth("shipper_a"))
    assert ok.status_code == 200 and ok.json()["status"] == "resolved" and ok.json()["detail"]["resolution"] == "request_replan"
    again = client.post(f"/v1/exceptions/{ex['id']}/resolve", json={"resolution": "accept_delay"}, headers=auth("carrier_b"))
    assert again.json()["detail"]["resolution"] == "request_replan"      # idempotent: không bị ghi đè
    after = get(client, "shipper_a", prop["id"])
    assert (after["status"], after["vehicle"]["id"], after["version"]) == (before["status"], before["vehicle"]["id"], before["version"])


def test_demo_endpoints_are_dispatcher_only_and_reset_is_complete(client):
    prop = _completed(client, actual=6.0)
    for user in ("shipper_a", "carrier_b", "node_c"):
        assert client.post("/v1/demo/reset", headers=auth(user)).status_code == 403
        assert client.post("/v1/demo/age-positions", headers=auth(user)).status_code == 403
        assert client.post("/v1/demo/scenarios/success/run", headers=auth(user)).status_code == 403
    assert client.post("/v1/demo/reset", headers=auth("dispatch")).status_code == 200
    with SessionLocal() as s:
        for model in (m.Proposal, m.Event, m.BenefitLedger, m.OutboxJob, m.Decision):
            assert s.execute(select(func.count()).select_from(model)).scalar_one() == 0, model.__name__
    assert client.get(f"/v1/proposals/{prop['id']}", headers=auth("shipper_a")).status_code == 404


def test_forwarder_cannot_self_verify_when_no_independent_party(client):
    """Lô của B do chính B chở (forwarder): cùng một tổ chức vừa báo vừa hưởng → không có bên độc lập → dừng ở 'measured'."""
    prop = match(client, "carrier_b", "LOT-B-011")["proposals"][0]
    act(client, "carrier_b", prop, "hold")
    act(client, "carrier_b", prop["id"], "accept"); act(client, "node_c", prop["id"], "accept"); run_worker(client)
    post_event(client, "carrier_b", prop["id"], "TRIP_STARTED"); run_worker(client)
    post_event(client, "carrier_b", prop["id"], "TRIP_COMPLETED", {"actual_empty_km": 4.0}); run_worker(client)
    row = _ledger(client, "carrier_b")["items"][0]
    assert row["status"] == "measured" and row["can_verify"] is False and row["verifier_independent_available"] is False
    r = client.post(f"/v1/benefits/{row['id']}/verify", headers=auth("carrier_b"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_INDEPENDENT_VERIFIER"


def test_only_the_carrier_that_owns_the_vehicle_can_report_trip_events(client):
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    confirm_all(client, prop); run_worker(client)
    for user in ("shipper_a", "shipper_a2", "node_c", "dispatch"):
        r = post_event(client, user, prop["id"], "TRIP_COMPLETED", {"actual_empty_km": 0})
        assert r.status_code == 403, (user, r.status_code)       # không bên nào khác được khai số đo
    assert get(client, "shipper_a", prop["id"])["status"] == "confirmed"
    assert _ledger(client)["items"] == []


def test_measurements_and_payloads_are_validated_at_ingest(client):
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    confirm_all(client, prop); run_worker(client)
    post_event(client, "carrier_b", prop["id"], "TRIP_STARTED"); run_worker(client)
    for bad in ({"actual_empty_km": -500}, {"actual_empty_km": 99999}, {"actual_empty_km": "abc"}, {"actual_empty_km": True}):
        assert post_event(client, "carrier_b", prop["id"], "TRIP_COMPLETED", bad).status_code == 422, bad
    for bad in ({}, {"delay_minutes": "abc"}, {"delay_minutes": -5}, {"delay_minutes": 0}, {"delay_minutes": 99999}):
        assert post_event(client, "carrier_b", prop["id"], "ETA_UPDATED", bad).status_code == 422, bad
    from sqlalchemy import func
    with SessionLocal() as s:  # sự kiện sai không được lưu, không để lại job độc
        assert s.execute(select(func.count()).select_from(m.OutboxJob).where(m.OutboxJob.status == "failed")).scalar_one() == 0
