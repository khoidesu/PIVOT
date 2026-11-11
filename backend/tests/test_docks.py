"""Truck Appointment: xếp dock tự động, chống trùng lịch, check-in/bốc dỡ/dwell, NO_SHOW, dời lịch khi ETA đổi, phân quyền."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app import models as m
from app.db import SessionLocal
from tests.conftest import auth
from tests.helpers import confirm_all, match, post_event, run_worker

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def confirmed(client, code="LOT-A-001"):
    return confirm_all(client, match(client, "shipper_a", code)["proposals"][0])


def board(client, user="node_c"):
    return client.get("/v1/docks/board", headers=auth(user)).json()


def appt_of(client, prop, user="node_c"):
    return next(a for a in board(client, user)["appointments"] if a["proposal_id"] == prop["id"])


def ev(client, user, pid, etype, at=None, sid=None, payload=None):
    return client.post("/v1/events", headers=auth(user), json={
        "entity_id": pid, "event_type": etype, "payload": payload or {}, "occurred_at": (at or NOW()).isoformat(),
        "source_system": "dock-test", "source_event_id": sid or str(uuid.uuid4())})


def overlaps(a, b):
    return a["window_start"] < b["window_end"] and b["window_start"] < a["window_end"]


def test_confirmation_books_a_dock_inside_the_slot_window_and_visibility_is_scoped(client):
    prop = confirmed(client)
    a = appt_of(client, prop)
    assert a["status"] == "scheduled" and a["dock_code"] in ("D1", "D2")
    slot_end = datetime.fromisoformat(prop["slot"]["end_at"]); slot_start = datetime.fromisoformat(prop["slot"]["start_at"])
    ws, we = datetime.fromisoformat(a["window_start"]), datetime.fromisoformat(a["window_end"])
    assert we - ws == timedelta(minutes=30) and ws >= slot_start and ws <= slot_end + timedelta(minutes=90)
    assert [x["proposal_id"] for x in board(client, "shipper_a")["appointments"]] == [prop["id"]]
    assert [x["proposal_id"] for x in board(client, "carrier_b")["appointments"]] == [prop["id"]]
    stranger = client.post("/v1/auth/login", json={"name": "Người lạ", "role": "carrier"}).json()["token"]
    sb = board(client, stranger)
    assert sb["appointments"] == [] and sb["docks"] == []


def test_many_confirmations_never_produce_overlapping_appointments_on_a_dock(client):
    for code in ("LOT-A-001", "LOT-A-002", "LOT-A-003", "LOT-A-004"):
        try:
            confirmed(client, code)
        except AssertionError:
            continue  # lô không có phương án khả thi: bỏ qua
    appts = [a for a in board(client)["appointments"] if a["status"] in ("scheduled", "checked_in", "unloading")]
    assert len(appts) >= 2
    for i, a in enumerate(appts):
        for b in appts[i + 1:]:
            assert not (a["dock_id"] == b["dock_id"] and overlaps(a, b)), (a, b)


def test_checkin_unload_complete_flow_computes_dwell_and_enforces_who_reports(client):
    prop = confirmed(client)
    pid = prop["id"]
    ev(client, "carrier_b", pid, "TRIP_STARTED"); run_worker(client)
    t = NOW()
    assert ev(client, "node_c", pid, "GATE_CHECK_IN").status_code == 403          # ICD không báo hộ xe đã đến
    assert ev(client, "shipper_a", pid, "UNLOAD_STARTED").status_code == 403
    assert ev(client, "carrier_b", pid, "UNLOAD_STARTED").status_code == 403
    assert ev(client, "dispatch", pid, "UNLOAD_STARTED").status_code == 403        # điều phối viên không phải ICD vận hành
    ev(client, "node_c", pid, "UNLOAD_STARTED", at=t - timedelta(minutes=30)); run_worker(client)
    assert appt_of(client, prop)["status"] == "scheduled"                          # chưa check-in → không bốc dỡ được
    assert ev(client, "carrier_b", pid, "GATE_CHECK_IN", at=t - timedelta(minutes=30), sid="ci-1").status_code == 202
    run_worker(client)
    assert appt_of(client, prop)["status"] == "checked_in"
    ev(client, "node_c", pid, "UNLOAD_STARTED", at=t - timedelta(minutes=20)); run_worker(client)
    assert appt_of(client, prop)["status"] == "unloading"
    ev(client, "node_c", pid, "UNLOAD_COMPLETED", at=t - timedelta(minutes=5), sid="done-1"); run_worker(client)
    a = appt_of(client, prop)
    assert a["status"] == "completed" and a["dwell_minutes"] == 25
    ev(client, "carrier_b", pid, "GATE_CHECK_IN", sid="ci-late"); run_worker(client)  # tin đến muộn không kéo lùi
    assert appt_of(client, prop)["status"] == "completed"
    assert board(client)["kpis"]["avg_dwell_minutes"] == 25


def test_no_show_and_queue_congestion_raise_exceptions_once(client):
    p1 = confirmed(client, "LOT-A-001")
    with SessionLocal() as s:
        s.execute(update(m.DockAppointment).where(m.DockAppointment.proposal_id == uuid.UUID(p1["id"])).values(window_end=NOW() - timedelta(hours=1), window_start=NOW() - timedelta(hours=2)))
        s.commit()
    run_worker(client); run_worker(client)
    assert appt_of(client, p1)["status"] == "no_show"
    rows = [e for e in client.get("/v1/exceptions", headers=auth("shipper_a")).json() if e["proposal_id"] == p1["id"] and e["exc_type"] == "NO_SHOW"]
    assert len(rows) == 1 and rows[0]["severity"] == "high" and {t["owner"] for t in rows[0]["tasks"] if t["kind"] == "human"} == {"node", "shipper"}


def test_long_wait_after_check_in_raises_dock_congestion_once(client):
    prop = confirmed(client)
    ev(client, "carrier_b", prop["id"], "TRIP_STARTED"); run_worker(client)
    ev(client, "carrier_b", prop["id"], "GATE_CHECK_IN", at=NOW() - timedelta(minutes=45)); run_worker(client)
    run_worker(client)
    rows = [e for e in client.get("/v1/exceptions", headers=auth("node_c")).json() if e["exc_type"] == "DOCK_CONGESTION"]
    assert len(rows) == 1 and rows[0]["detail"]["reason"] == "QUEUE"


def test_eta_delay_only_suggests_a_new_window_and_the_terminal_must_accept(client):
    prop = confirmed(client)
    before = appt_of(client, prop)
    assert ev(client, "carrier_b", prop["id"], "ETA_UPDATED", payload={"delay_minutes": 180}).status_code == 202
    run_worker(client)
    a = appt_of(client, prop)
    assert a["window_start"] == before["window_start"] and a["dock_id"] == before["dock_id"]   # KHÔNG tự dời
    assert a["suggestion"] and a["suggestion"]["reason"] == "ETA_DELAY" and a["late_minutes"] > 0
    assert datetime.fromisoformat(a["suggestion"]["window_start"]) >= datetime.fromisoformat(a["eta_at"])
    url = f"/v1/dock-appointments/{a['id']}/accept-suggestion"
    assert client.post(url, json={"version": a["version"]}, headers=auth("shipper_a")).status_code == 404
    assert client.post(url, json={"version": a["version"]}, headers=auth("carrier_b")).status_code == 404
    assert client.post(url, json={"version": a["version"] + 3}, headers=auth("node_c")).status_code == 409
    r = client.post(url, json={"version": a["version"]}, headers=auth("node_c"))
    assert r.status_code == 200 and r.json()["window_start"] == a["suggestion"]["window_start"]
    b = appt_of(client, prop)
    assert b["suggestion"] is None
    assert client.post(url, json={"version": b["version"]}, headers=auth("node_c")).status_code == 409   # không còn đề xuất


def test_concurrent_reschedules_to_the_same_window_allow_exactly_one(client):
    ps = []
    for code in ("LOT-A-001", "LOT-A-002", "LOT-A-003"):
        try:
            ps.append(confirmed(client, code))
        except AssertionError:
            pass
    assert len(ps) >= 2
    appts = [appt_of(client, p) for p in ps[:2]]
    dock = appts[0]["dock_id"]
    start = (NOW() + timedelta(hours=5)).replace(second=0, microsecond=0)
    start = start.replace(minute=(start.minute // 5) * 5)

    def go(a):
        return client.post(f"/v1/dock-appointments/{a['id']}/reschedule", headers=auth("node_c"),
                           json={"version": a["version"], "window_start": start.isoformat(), "dock_id": dock}).status_code
    with ThreadPoolExecutor(2) as ex:
        codes = sorted(ex.map(go, appts))
    assert codes == [200, 409]
    final = [a for a in board(client)["appointments"] if a["dock_id"] == dock and a["status"] == "scheduled"]
    for i, a in enumerate(final):
        for b in final[i + 1:]:
            assert not overlaps(a, b)


def test_reschedule_permissions_and_validation(client):
    prop = confirmed(client)
    a = appt_of(client, prop)
    url = f"/v1/dock-appointments/{a['id']}/reschedule"
    body = {"version": a["version"], "window_start": (NOW() + timedelta(hours=6)).isoformat()}
    assert client.post(url, json=body, headers=auth("carrier_b")).status_code == 404
    assert client.post(url, json=body, headers=auth("shipper_a")).status_code == 404
    assert client.post(url, json={**body, "dock_id": str(uuid.uuid4())}, headers=auth("node_c")).status_code == 422
    assert client.post(url, json={**body, "version": 99}, headers=auth("node_c")).status_code == 409
    assert client.post(url, json=body, headers=auth("dispatch")).status_code == 200      # điều phối viên được dời


def test_no_free_dock_window_raises_congestion_instead_of_forcing_a_booking(client):
    with SessionLocal() as s:
        s.execute(update(m.Dock).values(status="closed")); s.commit()
    prop = confirmed(client)
    assert board(client)["appointments"] == []
    rows = [e for e in client.get("/v1/exceptions", headers=auth("node_c")).json() if e["proposal_id"] == prop["id"]]
    assert len(rows) == 1 and rows[0]["exc_type"] == "DOCK_CONGESTION"


def test_replan_cancels_the_appointment_and_frees_the_window(client):
    prop = confirmed(client)
    a = appt_of(client, prop)
    r = client.post(f"/v1/proposals/{prop['id']}/replan", json={"version": prop["version"]}, headers=auth("shipper_a"))
    assert r.status_code == 200, r.text
    assert appt_of(client, prop)["status"] == "cancelled"
    assert a["id"] not in {x["id"] for x in board(client)["appointments"] if x["status"] == "scheduled"}
    with SessionLocal() as s:
        assert s.execute(select(m.DockAppointment.status).where(m.DockAppointment.id == uuid.UUID(a["id"]))).scalar_one() == "cancelled"
