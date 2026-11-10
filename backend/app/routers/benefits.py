import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from ..auth import Actor, current_actor
from ..benefits import service as bf
from ..booking.service import BookingError
from ..db import get_session

router = APIRouter(prefix="/v1")


@router.get("/benefits", response_model=s.BenefitListOut)
def list_benefits(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    rows = session.execute(select(m.BenefitLedger).order_by(m.BenefitLedger.verified_at.desc().nullslast())).scalars().all()
    items = [v for r in rows if (v := bf.view(session, actor, r))]
    return {"items": items, "totals": bf.totals(items)}


@router.get("/benefits/{benefit_id}", response_model=s.BenefitOut)
def get_benefit(benefit_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    row = session.get(m.BenefitLedger, benefit_id)
    v = bf.view(session, actor, row, detail=True) if row else None
    if v is None:
        raise HTTPException(status_code=404, detail="Benefit not found")
    return v


@router.post("/benefits/{benefit_id}/verify", response_model=s.BenefitOut)
def verify_benefit(benefit_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    try:
        row = bf.verify(session, actor, benefit_id, datetime.now(timezone.utc))
        session.commit()
    except BookingError as e:
        session.rollback()
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message, "reasons": []}) from None
    return bf.view(session, actor, row, detail=True)
