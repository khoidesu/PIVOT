import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from ..auth import Actor, current_actor
from ..booking import audit
from ..booking import service as bk
from ..db import get_session
from ..incidents import service as incidents

router = APIRouter(prefix="/v1")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _err(e: bk.BookingError):
    return HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})


@router.get("/exceptions")
def list_exceptions(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    now = _now()
    return [incidents.view(session, actor, ex, now) for ex in incidents.visible_exceptions(session, actor)]


@router.post("/exceptions/{exception_id}/resolve")
def resolve_exception(exception_id: uuid.UUID, body: s.ResolveIn, actor: Actor = Depends(current_actor),
                      session: Session = Depends(get_session)):
    """Người có quyền quyết định ngoại lệ; hệ thống không tự sửa/chuyển xe của chuyến đã cam kết."""
    now = _now()
    try:
        ex = audit.resolve_exception(session, actor, exception_id, body.resolution, body.note, now)
        ex.resolved_at = ex.resolved_at or now
        session.commit()
    except bk.BookingError as e:
        session.rollback()
        raise _err(e) from None
    return incidents.view(session, actor, ex, now)


@router.post("/exceptions/{exception_id}/tasks/{task_id}/complete")
def complete_task(exception_id: uuid.UUID, task_id: uuid.UUID, actor: Actor = Depends(current_actor),
                  session: Session = Depends(get_session)):
    now = _now()
    try:
        ex = incidents.complete_task(session, actor, exception_id, task_id, now)
        session.commit()
    except bk.BookingError as e:
        session.rollback()
        raise _err(e) from None
    return incidents.view(session, actor, ex, now)


@router.post("/proposals/{proposal_id}/replan")
def replan(proposal_id: uuid.UUID, body: s.ActionIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Ghép lại: huỷ chuyến đã cam kết chưa lấy hàng, trả tài nguyên, rồi chạy ghép mới để con người chọn."""
    from ..matching.service import run_match
    now = _now()
    try:
        prop = incidents.replan(session, actor, proposal_id, body.version, now)
        ship = session.get(m.Shipment, prop.shipment_id)
        run = run_match(session, actor, ship, now) if actor.role in ("shipper", "carrier") else None
        session.commit()
    except bk.BookingError as e:
        session.rollback()
        raise _err(e) from None
    return {"cancelled_proposal_id": prop.id, "shipment_id": ship.id, "shipment_status": ship.status,
            "run_id": run["run_id"] if run else None, "new_proposals": len(run["proposals"]) if run else 0}


def _mine(actor: Actor):
    return or_(and_(m.Notification.recipient_org_id == actor.org_id,
                    or_(m.Notification.recipient_role.is_(None), m.Notification.recipient_role == actor.role)),
               and_(m.Notification.recipient_org_id.is_(None), m.Notification.recipient_role == actor.role))


@router.get("/notifications")
def notifications(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    rows = session.execute(select(m.Notification).where(_mine(actor)).order_by(m.Notification.created_at.desc()).limit(100)).scalars().all()
    unread = sum(1 for r in rows if r.read_at is None and r.channel == "in_app")
    return {"unread": unread, "items": [{"id": r.id, "exception_id": r.exception_id, "channel": r.channel, "payload": r.payload,
                                         "created_at": r.created_at, "read": r.read_at is not None} for r in rows]}


@router.post("/notifications/read")
def mark_read(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    session.execute(update(m.Notification).where(_mine(actor), m.Notification.read_at.is_(None)).values(read_at=_now()))
    session.commit()
    return {"ok": True}
