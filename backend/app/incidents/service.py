"""Exception Management (brief Control Tower, chức năng 5): phân loại → mức độ → playbook → SLA → thông báo → leo thang → ghép lại.

Nguyên tắc giữ nguyên (CLAUDE.md mục 1): hệ thống ĐỀ XUẤT và nhắc, con người/đối tác quyết định; không tự đổi xe/chuyến đã cam kết.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import Actor
from ..booking import service as bk
from . import rules


def _parties(session: Session, prop: m.Proposal):
    ship, veh = session.get(m.Shipment, prop.shipment_id), session.get(m.Vehicle, prop.vehicle_id)
    slot = session.get(m.Slot, prop.slot_id) if prop.slot_id else None
    return ship, veh, slot, bk.party_orgs(ship, veh, slot)


def _notify(session: Session, ex: m.ExceptionRecord, prop: m.Proposal, now: datetime) -> None:
    ship, veh, _slot, orgs = _parties(session, prop)
    body = {"category": ex.exc_type, "severity": ex.severity, "shipment_code": ship.code, "plate": veh.plate,
            "sla_due_at": ex.sla_due_at.isoformat() if ex.sla_due_at else None}  # KHÔNG kèm giá/khách hàng/liên hệ (mô phỏng)
    recipients: list[tuple[uuid.UUID | None, str | None]] = [(o, None) for o in dict.fromkeys(orgs.values())]
    if ex.severity in ("high", "critical"):
        recipients.append((None, "dispatcher"))
    for channel in rules.CHANNELS[ex.severity]:
        for org_id, role in recipients:
            session.add(m.Notification(exception_id=ex.id, recipient_org_id=org_id, recipient_role=role, channel=channel,
                                       payload={**body, "simulated": channel != "in_app"}, created_at=now))


def raise_exception(session: Session, prop: m.Proposal, category: str, detail: dict, now: datetime, source: str = "event",
                    dedupe_key: str | None = None) -> m.ExceptionRecord | None:
    """Mở ngoại lệ (idempotent theo dedupe_key). Trả None nếu đã có (gửi lặp/worker restart không nhân đôi)."""
    if category not in rules.CATEGORIES:
        raise ValueError(f"unknown exception category {category}")
    if dedupe_key and session.execute(select(m.ExceptionRecord.id).where(m.ExceptionRecord.dedupe_key == dedupe_key)).first():
        return None
    sev = rules.severity_for(category, detail)
    ex = m.ExceptionRecord(proposal_id=prop.id, exc_type=category, status="open", severity=sev, playbook_id=category,
                           rule_version=f"{rules.RULE_VERSION}/{rules.PLAYBOOK_VERSION}", source=source, dedupe_key=dedupe_key,
                           detail=detail, created_at=now, sla_due_at=now + timedelta(minutes=rules.SLA_MINUTES[sev]))
    try:
        with session.begin_nested():
            session.add(ex)
            session.flush()
    except IntegrityError:
        return None
    for i, (key, kind, owner) in enumerate(rules.PLAYBOOKS[category]):
        t = m.ExceptionTask(exception_id=ex.id, step_key=key, kind=kind, owner=owner, position=i,
                            status="done" if kind == "auto" else "pending",
                            completed_by="system" if kind == "auto" else None, completed_at=now if kind == "auto" else None)
        session.add(t)
    _notify(session, ex, prop, now)
    session.flush()
    return ex


# ---------------------------------------------------------------- quyền
def _can_act_for(actor: Actor, owner: str, orgs: dict) -> bool:
    if actor.role == "dispatcher":
        return owner == "dispatcher"  # điều phối viên chỉ hoàn tất bước của mình, không thay đối tác quyết
    return owner in bk.actor_parties(actor, orgs)


def complete_task(session: Session, actor: Actor, exception_id: uuid.UUID, task_id: uuid.UUID, now: datetime) -> m.ExceptionRecord:
    from ..booking.audit import load_visible
    ex = session.execute(select(m.ExceptionRecord).where(m.ExceptionRecord.id == exception_id).with_for_update()).scalar_one_or_none()
    if ex is None:
        raise bk.BookingError("NOT_FOUND", "Exception not found", 404)
    prop, _s, _v, _sl, orgs = load_visible(session, actor, ex.proposal_id)
    task = session.get(m.ExceptionTask, task_id)
    if task is None or task.exception_id != ex.id:
        raise bk.BookingError("NOT_FOUND", "Task not found", 404)
    if not _can_act_for(actor, task.owner, orgs):
        raise bk.BookingError("FORBIDDEN", "Only the responsible party can complete this step", 403)
    if task.status == "pending":
        task.status, task.completed_by, task.completed_at = "done", f"{actor.user_name} · {actor.org_name}", now
        session.flush()
        if ex.status == "open" and all(t.status == "done" for t in tasks_of(session, ex.id)):
            ex.status, ex.resolved_at = "resolved", now
            ex.detail = {**(ex.detail or {}), "resolution": "playbook_completed"}
    return ex


def tasks_of(session: Session, exception_id: uuid.UUID) -> list[m.ExceptionTask]:
    return list(session.execute(select(m.ExceptionTask).where(m.ExceptionTask.exception_id == exception_id)
                                .order_by(m.ExceptionTask.position)).scalars())


# ---------------------------------------------------------------- quét nền (worker)
def sweep(session: Session, now: datetime, stale_minutes: int = 15) -> dict:
    """Leo thang ngoại lệ quá SLA + phát hiện dữ liệu vị trí quá cũ của chuyến đang chạy. Idempotent."""
    escalated = stale = 0
    for ex in session.execute(select(m.ExceptionRecord).where(
            m.ExceptionRecord.status == "open", m.ExceptionRecord.escalated_at.is_(None),
            m.ExceptionRecord.sla_due_at.is_not(None), m.ExceptionRecord.sla_due_at < now).with_for_update()).scalars():
        ex.escalated_at = now
        prop = session.get(m.Proposal, ex.proposal_id)
        ship, veh, *_ = _parties(session, prop)
        session.add(m.Notification(exception_id=ex.id, recipient_role="dispatcher", channel="in_app", created_at=now,
                                   payload={"category": ex.exc_type, "severity": ex.severity, "shipment_code": ship.code,
                                            "plate": veh.plate, "escalated": True, "simulated": False}))
        escalated += 1
    for prop, veh in session.execute(select(m.Proposal, m.Vehicle).join(m.Vehicle, m.Vehicle.id == m.Proposal.vehicle_id)
                                     .where(m.Proposal.status == "executing")).all():
        if veh.position_updated_at and veh.position_updated_at < now - timedelta(minutes=stale_minutes):
            age = int((now - veh.position_updated_at).total_seconds() // 60)
            if raise_exception(session, prop, "DATA_STALE", {"age_minutes": age}, now, source="sweep", dedupe_key=f"stale:{prop.id}"):
                stale += 1
    return {"escalated": escalated, "stale": stale}


# ---------------------------------------------------------------- ghép lại (đóng ngõ cụt "request_replan")
def replan(session: Session, actor: Actor, proposal_id: uuid.UUID, version: int, now: datetime) -> m.Proposal:
    """Huỷ chuyến đã cam kết CHƯA lấy hàng: trả xe/slot, lô về `open`, ngoại lệ đang mở đóng lại. Người dùng chủ động gọi — không tự đổi."""
    prop = bk.lock_proposal(session, proposal_id)
    ship, veh, slot = bk.lock_resources(session, prop)
    orgs = bk.party_orgs(ship, veh, slot)
    if not (bk.actor_parties(actor, orgs) & {"shipper", "carrier"}):
        raise bk.BookingError("NOT_FOUND" if actor.org_id not in orgs.values() and actor.role != "dispatcher" else "FORBIDDEN",
                              "Only the shipper or carrier of this trip can replan", 404 if actor.org_id not in orgs.values() and actor.role != "dispatcher" else 403)
    if prop.version != version:
        raise bk.BookingError("VERSION_CONFLICT", "Proposal changed; reload", 409)
    if prop.status not in ("confirmed", "executing"):
        raise bk.BookingError("INVALID_STATE", f"Cannot replan a '{prop.status}' trip", 409)
    from ..tracking.service import reached_milestones
    if reached_milestones(session, prop.id) & {"DEPARTED_PICKUP", "AT_ICD_GATE"}:
        raise bk.BookingError("CARGO_ON_BOARD", "Cargo already picked up; replanning is no longer possible", 409)
    breakdown = session.execute(select(m.ExceptionRecord.id).where(
        m.ExceptionRecord.proposal_id == prop.id, m.ExceptionRecord.exc_type == "BREAKDOWN")).first() is not None
    for r in session.execute(select(m.Reservation).where(m.Reservation.proposal_id == prop.id, m.Reservation.status.in_(("held", "committed")))
                             .with_for_update()).scalars():
        r.status = "released"
        if r.resource_type == "slot":
            bk._restore_slot(session, r.resource_id)
    prop.status, prop.version = "cancelled", prop.version + 1
    ship.status = "open"
    veh.status = "offline" if breakdown else "available"  # xe hỏng không được ghép lại cho tới khi báo khả dụng
    sim = session.get(m.SimTrip, prop.id)
    if sim:
        sim.running = False
    for ex in session.execute(select(m.ExceptionRecord).where(m.ExceptionRecord.proposal_id == prop.id, m.ExceptionRecord.status == "open")).scalars():
        ex.status, ex.resolved_at = "resolved", now
        ex.detail = {**(ex.detail or {}), "resolution": "replanned", "resolved_by": actor.user_name, "resolved_org": actor.org_name,
                     "resolved_at": now.isoformat()}
        for t in tasks_of(session, ex.id):
            if t.status == "pending":
                t.status, t.completed_by, t.completed_at = "done", f"{actor.user_name} · replan", now
    session.add(m.Decision(proposal_id=prop.id, actor_user_id=actor.user_id, actor_org_id=actor.org_id, action="replan",
                           party=None, proposal_version=prop.version))
    session.flush()
    return prop


# ---------------------------------------------------------------- đọc
def visible_exceptions(session: Session, actor: Actor, limit: int = 200) -> list[m.ExceptionRecord]:
    stmt = (select(m.ExceptionRecord).join(m.Proposal, m.Proposal.id == m.ExceptionRecord.proposal_id)
            .join(m.Shipment, m.Shipment.id == m.Proposal.shipment_id).join(m.Vehicle, m.Vehicle.id == m.Proposal.vehicle_id)
            .outerjoin(m.Slot, m.Slot.id == m.Proposal.slot_id))
    if actor.role != "dispatcher":
        stmt = stmt.where(or_(m.Shipment.tenant_id == actor.org_id, m.Vehicle.tenant_id == actor.org_id, m.Slot.node_org_id == actor.org_id))
    return list(session.execute(stmt.order_by(m.ExceptionRecord.created_at.desc()).limit(limit)).scalars())


def view(session: Session, actor: Actor, ex: m.ExceptionRecord, now: datetime) -> dict:
    prop = session.get(m.Proposal, ex.proposal_id)
    ship, veh, slot, orgs = _parties(session, prop)
    mine = bk.actor_parties(actor, orgs) | ({"dispatcher"} if actor.role == "dispatcher" else set())
    tasks = [{"id": str(t.id), "step_key": t.step_key, "kind": t.kind, "owner": t.owner, "status": t.status,
              "completed_by": t.completed_by, "completed_at": t.completed_at,
              "can_complete": t.status == "pending" and t.kind == "human" and t.owner in mine and ex.status == "open"}
             for t in tasks_of(session, ex.id)]
    overdue = ex.status == "open" and ex.sla_due_at is not None and ex.sla_due_at < now
    can_replan = (ex.status == "open" and prop.status in ("confirmed", "executing")
                  and bool(bk.actor_parties(actor, orgs) & {"shipper", "carrier"}))
    return {"id": ex.id, "proposal_id": ex.proposal_id, "exc_type": ex.exc_type, "status": ex.status, "detail": ex.detail or {},
            "created_at": ex.created_at, "severity": ex.severity, "playbook_id": ex.playbook_id, "rule_version": ex.rule_version,
            "source": ex.source, "sla_due_at": ex.sla_due_at, "escalated_at": ex.escalated_at, "resolved_at": ex.resolved_at,
            "overdue": overdue, "shipment_code": ship.code, "plate": veh.plate, "proposal_status": prop.status,
            "proposal_version": prop.version, "tasks": tasks, "can_replan": can_replan, "is_simulated": True}
