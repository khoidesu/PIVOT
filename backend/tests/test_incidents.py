"""Exception Management: phân mức theo luật, playbook + SLA, thông báo mô phỏng, leo thang, ghép lại, phân quyền."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app import models as m
from app.db import SessionLocal
from app.incidents import rules
from app.worker import process_pending
from tests.conftest import auth
from tests.helpers import act, confirm_all, get, match, post_event, run_worker, slot_remaining


def confirmed(client, code="LOT-A-001"):
    return confirm_all(client, match(client, "shipper_a", code)["proposals"][0])


def excs(client, user="shipper_a", pid=None):
    rows = client.get("/v1/exceptions", headers=auth(user)).json()
    return [e for e in rows if pid is None or e["proposal_id"] == pid]


# ---------------------------------------------------------------- luật
def test_severity_rules_are_deterministic_and_versioned():
    f = rules.severity_for
    assert [f("ETA_CHANGED", {"delay_minutes": d}) for d in (5, 15, 44, 45, 89, 90, 600)] == \
        ["low", "medium", "medium", "high", "high", "critical", "critical"]
    assert f("BREAKDOWN", {}) == "critical" and f("CARGO_DAMAGE", {}) == "high"
    assert f("DELAY_RISK", {"delay_minutes": 5, "cutoff_risk": True}) == "critical"
    assert set(rules.PLAYBOOKS) == set(rules.CATEGORIES)
    assert all(any(k == "human" for _, k, _ in steps) or c == "ETA_CHANGED" for c, steps in rules.PLAYBOOKS.items())
    assert rules.RULE_VERSION and rules.PLAYBOOK_VERSION


# ---------------------------------------------------------------- phát hiện + playbook + thông báo
def test_eta_delay_opens_leveled_exception_with_playbook_sla_and_notifications(client):
    prop = confirmed(client)
    assert post_event(client, "carrier_b", prop["id"], "ETA_UPDATED", {"delay_minutes": 60}).status_code == 202
    run_worker(client)
    [ex] = excs(client, pid=prop["id"])
    assert ex["exc_type"] == "ETA_CHANGED" and ex["severity"] == "high" and ex["status"] == "open"
    assert ex["rule_version"] == f"{rules.RULE_VERSION}/{rules.PLAYBOOK_VERSION}"
    assert [t["status"] for t in ex["tasks"]][0] == "done" and {t["owner"] for t in ex["tasks"] if t["kind"] == "human"} == {"carrier", "shipper"}
    created = datetime.fromisoformat(ex["created_at"]); due = datetime.fromisoformat(ex["sla_due_at"])
    assert due - created == timedelta(minutes=rules.SLA_MINUTES["high"])
    with SessionLocal() as s:
        ns = s.execute(select(m.Notification).where(m.Notification.exception_id == uuid.UUID(ex["id"]))).scalars().all()
    assert {n.channel for n in ns} == {"in_app", "email_sim"}                 # mức high: in-app + email giả lập
    assert any(n.recipient_role == "dispatcher" for n in ns)                  # điều phối viên được báo ở mức high
    for n in ns:                                                              # không PII / thương mại
        assert set(n.payload) <= {"category", "severity", "shipment_code", "plate", "sla_due_at", "simulated", "escalated"}
        assert n.payload["simulated"] is (n.channel != "in_app")


def test_duplicate_events_never_open_a_second_exception(client):
    prop = confirmed(client)
    for _ in range(4):
        post_event(client, "carrier_b", prop["id"], "ETA_UPDATED", {"delay_minutes": 30}, source_event_id="eta-dup")
    run_worker(client); run_worker(client)
    assert len(excs(client, pid=prop["id"])) == 1
    with SessionLocal() as s:  # worker áp dụng lại cùng sự kiện (restart) cũng không nhân đôi
        ev = s.execute(select(m.Event).where(m.Event.source_event_id == "eta-dup")).scalar_one()
        from app.events.service import _exception
        p = s.get(m.Proposal, uuid.UUID(prop["id"]))
        _exception(s, p, ev, "ETA_CHANGED", {"delay_minutes": 30}); s.commit()
    assert len(excs(client, pid=prop["id"])) == 1


def test_breakdown_is_critical_with_sms_and_email_sim_and_only_owner_carrier_can_report(client):
    prop = confirmed(client)
    assert post_event(client, "shipper_a", prop["id"], "INCIDENT_REPORTED", {"kind": "BREAKDOWN"}).status_code == 403
    assert post_event(client, "node_c", prop["id"], "INCIDENT_REPORTED", {"kind": "BREAKDOWN"}).status_code == 403
    assert post_event(client, "carrier_b", prop["id"], "INCIDENT_REPORTED", {"kind": "FLOOD"}).status_code == 422
    assert post_event(client, "carrier_b", prop["id"], "INCIDENT_REPORTED", {"kind": "BREAKDOWN", "note": "x" * 301}).status_code == 422
    assert post_event(client, "carrier_b", prop["id"], "INCIDENT_REPORTED", {"kind": "BREAKDOWN", "note": "Nổ lốp"}).status_code == 202
    run_worker(client)
    [ex] = excs(client, pid=prop["id"])
    assert ex["exc_type"] == "BREAKDOWN" and ex["severity"] == "critical"
    with SessionLocal() as s:
        chans = {n.channel for n in s.execute(select(m.Notification).where(m.Notification.exception_id == uuid.UUID(ex["id"]))).scalars()}
    assert chans == {"in_app", "sms_sim", "email_sim"}


def test_cargo_damage_reported_by_node(client):
    prop = confirmed(client)
    assert post_event(client, "node_c", prop["id"], "CARGO_DAMAGE_REPORTED", {"note": "Thùng móp"}).status_code == 202
    run_worker(client)
    [ex] = excs(client, "node_c", prop["id"])
    assert ex["exc_type"] == "CARGO_DAMAGE" and ex["severity"] == "high"
    assert {"node", "carrier", "shipper"} == {t["owner"] for t in ex["tasks"] if t["kind"] == "human"}


# ---------------------------------------------------------------- playbook & phân quyền
def test_only_the_responsible_party_completes_a_step_and_playbook_resolves_when_done(client):
    prop = confirmed(client)
    post_event(client, "carrier_b", prop["id"], "ETA_UPDATED", {"delay_minutes": 20}); run_worker(client)
    [ex] = excs(client, pid=prop["id"])
    carrier_task = next(t for t in ex["tasks"] if t["owner"] == "carrier"); shipper_task = next(t for t in ex["tasks"] if t["owner"] == "shipper")
    url = lambda t: f"/v1/exceptions/{ex['id']}/tasks/{t['id']}/complete"  # noqa: E731
    assert client.post(url(carrier_task), headers=auth("shipper_a")).status_code == 403
    assert client.post(url(carrier_task), headers=auth("dispatch")).status_code == 403      # điều phối viên không thay đối tác quyết
    assert client.post(url(carrier_task), headers=auth("carrier_b")).status_code == 200
    r = client.post(url(shipper_task), headers=auth("shipper_a"))
    assert r.status_code == 200 and r.json()["status"] == "resolved" and r.json()["detail"]["resolution"] == "playbook_completed"
    stranger = client.post("/v1/auth/login", json={"name": "Người lạ", "role": "shipper"}).json()["token"]
    assert client.post(url(shipper_task), headers=auth(stranger)).status_code == 404         # không lộ sự tồn tại
    assert excs(client, stranger) == []


# ---------------------------------------------------------------- SLA / leo thang / dữ liệu cũ
def test_overdue_exception_escalates_once_to_dispatcher(client):
    prop = confirmed(client)
    post_event(client, "carrier_b", prop["id"], "ETA_UPDATED", {"delay_minutes": 50}); run_worker(client)
    [ex] = excs(client, pid=prop["id"])
    with SessionLocal() as s:
        s.execute(update(m.ExceptionRecord).where(m.ExceptionRecord.id == uuid.UUID(ex["id"])).values(sla_due_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        s.commit()
    run_worker(client); run_worker(client)
    [ex2] = excs(client, pid=prop["id"])
    assert ex2["escalated_at"] and ex2["overdue"] is True
    with SessionLocal() as s:
        n = s.execute(select(m.Notification).where(m.Notification.exception_id == uuid.UUID(ex["id"]), m.Notification.payload["escalated"].as_boolean().is_(True))).scalars().all()
    assert len(n) == 1 and n[0].recipient_role == "dispatcher"


def test_stale_position_of_a_running_trip_raises_data_stale_once(client):
    prop = confirmed(client)
    post_event(client, "carrier_b", prop["id"], "TRIP_STARTED"); run_worker(client)
    with SessionLocal() as s:
        vid = s.get(m.Proposal, uuid.UUID(prop["id"])).vehicle_id
        s.execute(update(m.Vehicle).where(m.Vehicle.id == vid).values(position_updated_at=datetime.now(timezone.utc) - timedelta(minutes=40)))
        s.commit()
    run_worker(client); run_worker(client)
    rows = [e for e in excs(client, pid=prop["id"]) if e["exc_type"] == "DATA_STALE"]
    assert len(rows) == 1 and rows[0]["severity"] == "medium" and rows[0]["source"] == "sweep"


# ---------------------------------------------------------------- ghép lại
def test_replan_releases_everything_and_returns_the_lot_to_open(client):
    prop = confirmed(client)
    slot_id = prop["slot"]["id"]
    before = slot_remaining(slot_id)
    post_event(client, "carrier_b", prop["id"], "ETA_UPDATED", {"delay_minutes": 70}); run_worker(client)
    r = client.post(f"/v1/proposals/{prop['id']}/replan", json={"version": get(client, "shipper_a", prop["id"])["version"]}, headers=auth("shipper_a"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["shipment_status"] == "open" and body["new_proposals"] >= 1
    assert get(client, "shipper_a", prop["id"])["status"] == "cancelled"
    assert slot_remaining(slot_id) == before + 1  # slot cũ được trả đủ một chỗ (ghép lại chỉ đề xuất, chưa giữ)
    [ex] = excs(client, pid=prop["id"])
    assert ex["status"] == "resolved" and ex["detail"]["resolution"] == "replanned"
    assert all(t["status"] == "done" for t in ex["tasks"])
    assert act(client, "shipper_a", prop["id"], "accept", version=99).status_code in (404, 409, 422)  # chuyến đã huỷ không nhận xác nhận


def test_replan_guards_permissions_version_state_and_cargo_on_board(client):
    prop = confirmed(client)
    v = lambda: get(client, "shipper_a", prop["id"])["version"]  # noqa: E731
    assert client.post(f"/v1/proposals/{prop['id']}/replan", json={"version": v()}, headers=auth("node_c")).status_code == 403
    assert client.post(f"/v1/proposals/{prop['id']}/replan", json={"version": v()}, headers=auth("dispatch")).status_code == 403
    assert client.post(f"/v1/proposals/{prop['id']}/replan", json={"version": v() + 5}, headers=auth("shipper_a")).status_code == 409
    stranger = client.post("/v1/auth/login", json={"name": "Người lạ", "role": "carrier"}).json()["token"]
    assert client.post(f"/v1/proposals/{prop['id']}/replan", json={"version": v()}, headers=auth(stranger)).status_code == 404
    post_event(client, "carrier_b", prop["id"], "TRIP_STARTED"); run_worker(client)
    with SessionLocal() as s:  # xe đã lấy hàng (mốc DEPARTED_PICKUP) → không còn ghép lại được
        p = s.get(m.Proposal, uuid.UUID(prop["id"]))
        s.add(m.Event(tenant_id=s.get(m.Vehicle, p.vehicle_id).tenant_id, entity_type="proposal", entity_id=p.id, event_type="MILESTONE_REACHED",
                      occurred_at=datetime.now(timezone.utc), source_system="system", source_event_id=f"ms:{p.id}:DEPARTED_PICKUP",
                      quality_status="applied", payload={"milestone": "DEPARTED_PICKUP"}))
        s.commit()
    r = client.post(f"/v1/proposals/{prop['id']}/replan", json={"version": v()}, headers=auth("carrier_b"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CARGO_ON_BOARD"


def test_replan_after_breakdown_takes_the_vehicle_offline_so_it_is_not_reoffered(client):
    prop = confirmed(client)
    plate = prop["vehicle"]["plate"]
    post_event(client, "carrier_b", prop["id"], "INCIDENT_REPORTED", {"kind": "BREAKDOWN"}); run_worker(client)
    r = client.post(f"/v1/proposals/{prop['id']}/replan", json={"version": get(client, "shipper_a", prop["id"])["version"]}, headers=auth("carrier_b"))
    assert r.status_code == 200, r.text
    props = client.get("/v1/proposals", headers=auth("shipper_a"), params={"shipment_id": prop["shipment"]["id"]}).json()
    assert plate not in {p["vehicle"]["plate"] for p in props if p["status"] in ("proposed", "pending_acceptance")}


# ---------------------------------------------------------------- thông báo
def test_notifications_are_scoped_per_recipient_and_can_be_marked_read(client):
    prop = confirmed(client)
    post_event(client, "carrier_b", prop["id"], "INCIDENT_REPORTED", {"kind": "BREAKDOWN"}); run_worker(client)
    for user in ("shipper_a", "carrier_b", "node_c", "dispatch"):
        d = client.get("/v1/notifications", headers=auth(user)).json()
        assert d["unread"] >= 1, user
    stranger = client.post("/v1/auth/login", json={"name": "Người lạ", "role": "shipper"}).json()["token"]
    assert client.get("/v1/notifications", headers=auth(stranger)).json() == {"unread": 0, "items": []}
    assert client.post("/v1/notifications/read", headers=auth("shipper_a")).status_code == 200
    assert client.get("/v1/notifications", headers=auth("shipper_a")).json()["unread"] == 0
    assert client.get("/v1/notifications", headers=auth("carrier_b")).json()["unread"] >= 1  # đọc của người này không xoá của người khác
