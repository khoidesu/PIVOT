import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import Actor, current_actor
from ..booking import service as bk
from ..db import get_session
from ..docks import service as docks

router = APIRouter(prefix="/v1")


class RescheduleIn(BaseModel):
    version: int = Field(ge=1)
    window_start: AwareDatetime
    dock_id: uuid.UUID | None = None


class VersionIn(BaseModel):
    version: int = Field(ge=1)


def _err(e: bk.BookingError):
    return HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})


@router.get("/docks/board")
def board(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Lịch dock theo quyền: ICD thấy mọi lịch của mình; chủ hàng/nhà vận tải chỉ thấy lịch của mình + các khung 'bận' ẩn danh."""
    return docks.board(session, actor, datetime.now(timezone.utc))


@router.post("/dock-appointments/{appointment_id}/reschedule")
def reschedule(appointment_id: uuid.UUID, body: RescheduleIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    try:
        appt = docks.reschedule(session, actor, appointment_id, body.version, body.window_start, body.dock_id)
        session.commit()
    except bk.BookingError as e:
        session.rollback()
        raise _err(e) from None
    return {"id": appt.id, "version": appt.version, "window_start": appt.window_start, "window_end": appt.window_end, "dock_id": appt.dock_id}


@router.post("/dock-appointments/{appointment_id}/accept-suggestion")
def accept_suggestion(appointment_id: uuid.UUID, body: VersionIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    try:
        appt = docks.accept_suggestion(session, actor, appointment_id, body.version)
        session.commit()
    except bk.BookingError as e:
        session.rollback()
        raise _err(e) from None
    return {"id": appt.id, "version": appt.version, "window_start": appt.window_start, "window_end": appt.window_end, "dock_id": appt.dock_id}
