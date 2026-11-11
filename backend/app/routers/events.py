import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from ..admin import require_admin
from ..auth import Actor, current_actor
from ..booking import audit
from ..booking import service as bk
from ..db import SessionLocal, get_session
from ..events import service as events
from ..worker import process_pending, replay

router = APIRouter(prefix="/v1")


def _dispatcher_only(actor: Actor) -> None:
    if actor.role != "dispatcher":
        raise HTTPException(status_code=403, detail="Dispatcher only")


@router.post("/events", response_model=s.EventOut, status_code=202)
def post_event(body: s.EventIn, response: Response, actor: Actor = Depends(current_actor),
               session: Session = Depends(get_session)):
    """Nhận sự kiện idempotent. Gửi lại cùng (source_system, source_event_id) → 200 duplicate, không tác động thứ hai."""
    try:
        ev, duplicate = events.ingest(session, actor, body.model_dump(), datetime.now(timezone.utc))
        session.commit()
    except bk.BookingError as e:
        session.rollback()
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message}) from None
    if duplicate:
        response.status_code = 200
    return s.EventOut(event_id=ev.id, duplicate=duplicate, quality_status=ev.quality_status)


@router.get("/outbox", response_model=list[s.OutboxOut])
def list_outbox(status: str | None = None, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    _dispatcher_only(actor)
    stmt = select(m.OutboxJob).order_by(m.OutboxJob.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(m.OutboxJob.status == status)
    return session.execute(stmt).scalars().all()


@router.post("/outbox/{job_id}/replay", response_model=s.OutboxOut)
def replay_job(job_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    _dispatcher_only(actor)
    job = replay(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    session.commit()
    return job


@router.post("/demo/worker/run", dependencies=[Depends(require_admin)])
def run_worker_once(simulate_crash: bool = False, advance_seconds: int = 0, actor: Actor = Depends(current_actor)):
    """Chạy worker một lượt ngay (demo/test). Worker nền cũng tự chạy mỗi giây khi bật PIVOT_WORKER_INLINE.

    simulate_crash: worker "chết" sau khi áp tác động nhưng trước commit (kịch bản worker restart).
    advance_seconds: coi như thời gian đã trôi để job đang backoff được xử lý lại ngay.
    """
    _dispatcher_only(actor)
    now = datetime.now(timezone.utc) + timedelta(seconds=max(0, min(advance_seconds, 3600)))

    def crash(_job):
        raise RuntimeError("simulated worker crash before commit")
    return process_pending(SessionLocal, now=now, fail_hook=crash if simulate_crash else None)
