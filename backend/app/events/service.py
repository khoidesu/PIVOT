"""Sự kiện idempotent + áp dụng tác động nghiệp vụ (DRAFT 4.1).

- Unique (source_system, source_event_id): gửi lại → trả bản ghi cũ, KHÔNG tạo tác động thứ hai.
- ingest chỉ lưu sự kiện gốc + ghi outbox job trong CÙNG transaction; worker mới áp dụng tác động (consumer idempotent).
- Tin đến muộn / sai thứ tự không kéo trạng thái lùi (vd TRIP_STARTED sau completed → quality_status='late').
- ETA đổi: đề xuất CHƯA cam kết → hết hiệu lực để tính lại; chuyến ĐÃ cam kết → chỉ tạo ngoại lệ xin quyết định,
  không tự sửa/chuyển xe.
"""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import Actor
from ..booking import service as bk

SUPPORTED = {"TRIP_STARTED", "TRIP_COMPLETED", "ETA_UPDATED"}
FINAL_QUALITY = {"applied", "late", "invalid"}


def ingest(session: Session, actor: Actor, body: dict, now: datetime) -> tuple[m.Event, bool]:
    prop = session.get(m.Proposal, body["entity_id"])
    if prop is None:
        raise bk.BookingError("NOT_FOUND", "Entity not found", 404)
    ship = session.get(m.Shipment, prop.shipment_id)
    veh = session.get(m.Vehicle, prop.vehicle_id)
    slot = session.get(m.Slot, prop.slot_id) if prop.slot_id else None
    if actor.org_id not in bk.party_orgs(ship, veh, slot).values():  # chỉ bên liên quan được báo sự kiện
        raise bk.BookingError("NOT_FOUND", "Entity not found", 404)

    ev = m.Event(tenant_id=actor.org_id, entity_type="proposal", entity_id=prop.id, event_type=body["event_type"],
                 occurred_at=body["occurred_at"], received_at=now, source_system=body["source_system"],
                 source_event_id=body["source_event_id"], payload=body.get("payload") or {},
                 correlation_id=body.get("correlation_id"),
                 quality_status="ok" if body["event_type"] in SUPPORTED else "unsupported")
    try:
        with session.begin_nested():
            session.add(ev)
            session.flush()
    except IntegrityError:
        existing = session.execute(select(m.Event).where(
            m.Event.source_system == body["source_system"],
            m.Event.source_event_id == body["source_event_id"])).scalar_one()
        if existing.tenant_id != actor.org_id:  # không lộ sự kiện của tổ chức khác
            raise bk.BookingError("CONFLICT", "source_event_id already used", 409) from None
        return existing, True
    if body["event_type"] in SUPPORTED:
        session.add(m.OutboxJob(topic="event.apply", payload={"event_id": str(ev.id)}, dedupe_key=f"apply:{ev.id}"))
    return ev, False


def _exception(session: Session, prop: m.Proposal, ev: m.Event, exc_type: str, detail: dict) -> None:
    for e in session.execute(select(m.ExceptionRecord).where(m.ExceptionRecord.proposal_id == prop.id)).scalars():
        if (e.detail or {}).get("event_id") == str(ev.id):
            return  # đã tạo cho sự kiện này (idempotent)
    session.add(m.ExceptionRecord(proposal_id=prop.id, exc_type=exc_type, status="open",
                                  detail={**detail, "event_id": str(ev.id)}))


def apply_event(session: Session, event_id: uuid.UUID, now: datetime) -> str:
    ev = session.get(m.Event, event_id)
    if ev is None or ev.quality_status in FINAL_QUALITY:
        return "skipped"  # đã xử lý rồi → không nhân đôi tác động
    prop = bk.lock_proposal(session, ev.entity_id)
    ship, veh, slot = bk.lock_resources(session, prop)
    status = prop.status

    if ev.event_type == "TRIP_STARTED":
        if status == "confirmed":
            prop.status, ev.quality_status = "executing", "applied"
            prop.version += 1
        else:  # đến muộn (đã executing/completed) hoặc chưa được xác nhận
            ev.quality_status = "late" if status in ("executing", "completed") else "invalid"

    elif ev.event_type == "TRIP_COMPLETED":
        if status == "executing":
            prop.status, ev.quality_status = "completed", "applied"
            prop.version += 1
            ship.status, veh.status = "completed", "available"
            for r in session.execute(select(m.Reservation).where(
                    m.Reservation.proposal_id == prop.id, m.Reservation.status == "committed")).scalars():
                r.status = "released"  # tài nguyên được trả sau khi hoàn tất
        else:
            ev.quality_status = "late" if status == "completed" else "invalid"

    elif ev.event_type == "ETA_UPDATED":
        delay = int((ev.payload or {}).get("delay_minutes", 0))
        if status in bk.OPEN_STATES:
            bk.release_holds(session, prop.id, "expired")
            prop.status = "expired"
            prop.version += 1
            _exception(session, prop, ev, "ETA_CHANGED", {"delay_minutes": delay, "action": "proposal_expired_recompute"})
            ev.quality_status = "applied"
        elif status in ("confirmed", "executing"):
            _exception(session, prop, ev, "ETA_CHANGED", {"delay_minutes": delay, "action": "needs_decision"})
            ev.quality_status = "applied"  # chỉ tạo ngoại lệ; KHÔNG sửa chuyến đã cam kết
        else:
            ev.quality_status = "late" if status == "completed" else "invalid"
    session.flush()
    return ev.quality_status
