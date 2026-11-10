"""Sự kiện idempotent, tin đến muộn, ETA đổi → ngoại lệ, worker restart (DRAFT bảng 5, kịch bản demo 5 & 6)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app import models as m
from app.db import SessionLocal
from app.events import service as events
from app.worker import MAX_ATTEMPTS, process_pending
from tests.conftest import auth
from tests.helpers import act, confirm_all, get, match, post_event, run_worker


def _confirmed(client, code="LOT-A-001"):
    confirmed = confirm_all(client, match(client, "shipper_a", code)["proposals"][0])
    run_worker(client)  # xử lý job proposal.confirmed để hàng đợi chỉ còn job của sự kiện đang thử
    return confirmed


def _count(model, *where):
    with SessionLocal() as s:
        return s.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


def test_event_sent_ten_times_has_one_effect(client):
    pid = _confirmed(client)["id"]
    results = [post_event(client, "carrier_b", pid, "TRIP_STARTED", source_event_id="evt-1") for _ in range(10)]
    assert [r.status_code for r in results] == [202] + [200] * 9
    assert len({r.json()["event_id"] for r in results}) == 1 and all(r.json()["duplicate"] for r in results[1:])
    run_worker(client)
    run_worker(client)
    view = get(client, "shipper_a", pid)
    assert view["status"] == "executing"
    assert view["version"] == 4  # proposed(1)→pending(2)→confirmed(3)→executing(4): đúng một lần
    assert _count(m.Event, m.Event.source_event_id == "evt-1") == 1
    assert _count(m.OutboxJob, m.OutboxJob.topic == "event.apply") == 1


def test_late_event_never_moves_state_backwards(client):
    pid = _confirmed(client)["id"]
    post_event(client, "carrier_b", pid, "TRIP_STARTED")
    run_worker(client)
    post_event(client, "carrier_b", pid, "TRIP_COMPLETED")
    run_worker(client)
    assert get(client, "shipper_a", pid)["status"] == "completed"
    late = post_event(client, "carrier_b", pid, "TRIP_STARTED")      # tin muộn khác source_event_id
    run_worker(client)
    assert get(client, "shipper_a", pid)["status"] == "completed"    # KHÔNG lùi về executing
    with SessionLocal() as s:
        assert s.get(m.Event, uuid.UUID(late.json()["event_id"])).quality_status == "late"


def test_out_of_order_complete_before_start_is_not_applied(client):
    pid = _confirmed(client)["id"]
    ev = post_event(client, "carrier_b", pid, "TRIP_COMPLETED")
    run_worker(client)
    assert get(client, "shipper_a", pid)["status"] == "confirmed"
    with SessionLocal() as s:
        assert s.get(m.Event, uuid.UUID(ev.json()["event_id"])).quality_status == "invalid"


def test_eta_change_on_committed_trip_creates_exception_without_touching_trip(client):
    confirmed = _confirmed(client)
    pid = confirmed["id"]
    post_event(client, "carrier_b", pid, "TRIP_STARTED")
    run_worker(client)
    before = get(client, "shipper_a", pid)
    post_event(client, "carrier_b", pid, "ETA_UPDATED", {"delay_minutes": 45})
    run_worker(client)
    after = get(client, "shipper_a", pid)
    assert (after["status"], after["vehicle"]["id"], after["version"]) == (before["status"], before["vehicle"]["id"], before["version"])
    excs = client.get("/v1/exceptions", headers=auth("shipper_a")).json()
    assert len(excs) == 1 and excs[0]["exc_type"] == "ETA_CHANGED" and excs[0]["detail"]["action"] == "needs_decision"
    assert excs[0]["detail"]["delay_minutes"] == 45


def test_eta_change_invalidates_uncommitted_proposal(client):
    prop = match(client, "shipper_a", "LOT-A-001")["proposals"][0]
    held = act(client, "shipper_a", prop, "hold").json()
    post_event(client, "carrier_b", held["id"], "ETA_UPDATED", {"delay_minutes": 90})
    run_worker(client)
    view = get(client, "shipper_a", held["id"])
    assert view["status"] == "expired"                                # phương án cũ không còn phù hợp
    assert client.get("/v1/exceptions", headers=auth("carrier_b")).json()[0]["detail"]["action"] == "proposal_expired_recompute"
    assert match(client, "shipper_a", "LOT-A-001")["status"] in ("proposals", "no_feasible_option")  # tính lại được


def test_applying_the_same_event_twice_does_not_duplicate_effects(client):
    pid = _confirmed(client)["id"]
    ev = post_event(client, "carrier_b", pid, "ETA_UPDATED", {"delay_minutes": 10}).json()["event_id"]
    now = datetime.now(timezone.utc)
    with SessionLocal() as s:
        assert events.apply_event(s, uuid.UUID(ev), now) == "applied"
        assert events.apply_event(s, uuid.UUID(ev), now) == "skipped"
        s.commit()
    assert _count(m.ExceptionRecord) == 1


def test_worker_crash_midway_loses_nothing_and_applies_once(client):
    pid = _confirmed(client)["id"]
    post_event(client, "carrier_b", pid, "TRIP_STARTED")
    t0 = datetime.now(timezone.utc)

    def crash(job):  # worker chết SAU khi áp tác động nhưng TRƯỚC khi commit
        raise RuntimeError("worker killed")
    stats = process_pending(now=t0, fail_hook=crash)
    assert stats == {"done": 0, "retry": 1, "failed": 0}
    assert get(client, "shipper_a", pid)["status"] == "confirmed"      # không có tác động nửa vời
    assert process_pending(now=t0)["done"] == 0                        # còn lease/backoff → chưa xử lý lại ngay
    assert process_pending(now=t0 + timedelta(minutes=2))["done"] == 1  # "worker restart": xử lý lại đúng một lần
    assert get(client, "shipper_a", pid)["status"] == "executing"
    assert process_pending(now=t0 + timedelta(minutes=5))["done"] == 0


def test_failed_jobs_stop_retrying_and_can_be_replayed(client):
    pid = _confirmed(client)["id"]
    post_event(client, "carrier_b", pid, "TRIP_STARTED")
    t = datetime.now(timezone.utc)

    def boom(job):
        raise RuntimeError("boom")
    for i in range(MAX_ATTEMPTS):
        process_pending(now=t + timedelta(minutes=10 * (i + 1)), fail_hook=boom)
    failed = client.get("/v1/outbox?status=failed", headers=auth("dispatch")).json()
    assert len(failed) == 1 and failed[0]["attempts"] == MAX_ATTEMPTS and "boom" in failed[0]["last_error"]
    assert process_pending(now=t + timedelta(hours=5))["done"] == 0    # không retry vô hạn
    assert client.post(f"/v1/outbox/{failed[0]['id']}/replay", headers=auth("carrier_b")).status_code == 403
    assert client.post(f"/v1/outbox/{failed[0]['id']}/replay", headers=auth("dispatch")).status_code == 200
    assert process_pending(now=t + timedelta(hours=6))["done"] == 1
    assert get(client, "shipper_a", pid)["status"] == "executing"


def test_confirmed_outbox_job_is_written_with_the_state_change(client):
    pid = _confirmed(client)["id"]
    assert _count(m.OutboxJob, m.OutboxJob.dedupe_key == f"proposal.confirmed:{pid}") == 1
    run_worker(client)
    with SessionLocal() as s:
        assert s.execute(select(m.OutboxJob.status).where(m.OutboxJob.dedupe_key == f"proposal.confirmed:{pid}")).scalar_one() == "done"


def test_event_validation_authorization_and_unknown_types(client):
    pid = _confirmed(client)["id"]
    bad = client.post("/v1/events", headers=auth("carrier_b"), json={
        "entity_id": pid, "event_type": "TRIP_STARTED", "occurred_at": "2026-01-01T00:00:00",  # thiếu múi giờ
        "source_system": "x", "source_event_id": "y"})
    assert bad.status_code == 422
    future = post_event(client, "carrier_b", pid, "TRIP_STARTED")  # hợp lệ
    assert future.status_code == 202
    from datetime import timedelta
    far = client.post("/v1/events", headers=auth("carrier_b"), json={
        "entity_id": pid, "event_type": "TRIP_STARTED", "occurred_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "source_system": "x", "source_event_id": "future-1"})
    assert far.status_code == 422                                       # sự kiện từ tương lai là dữ liệu lỗi
    assert post_event(client, "carrier_b", str(uuid.uuid4()), "TRIP_STARTED").status_code == 404
    for user in ("shipper_a", "node_c", "dispatch"):                    # chỉ nhà vận tải sở hữu xe được báo sự kiện chuyến
        assert post_event(client, user, pid, "TRIP_STARTED").status_code == 403
    unknown = post_event(client, "carrier_b", pid, "SOMETHING_ELSE")
    assert unknown.status_code == 202 and unknown.json()["quality_status"] == "unsupported"
