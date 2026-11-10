import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from ..access import get_visible_shipment
from ..auth import Actor, current_actor
from ..booking import audit
from ..booking import service as bk
from ..booking.views import proposal_view, proposal_views
from ..db import get_session
from ..matching.service import run_match

router = APIRouter(prefix="/v1")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _http(e: bk.BookingError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message, "reasons": e.reasons})


@router.post("/match-runs", response_model=s.MatchRunOut)
def create_match_run(body: s.MatchRunIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    shipment = get_visible_shipment(session, actor, body.shipment_id)
    now = _now()
    run = run_match(session, actor, shipment, now)
    session.commit()
    from ..matching.redact import redact_rejections
    vids = {r["vehicle_id"] for r in run["rejections"] + run["needs_data"]}
    veh_org = {str(v.id): v.tenant_id for v in session.query(m.Vehicle).filter(m.Vehicle.id.in_(vids))} if vids else {}
    return {**run, "proposals": proposal_views(session, actor, run["proposals"], now),
            "rejections": redact_rejections(run["rejections"], veh_org, actor),
            "needs_data": redact_rejections(run["needs_data"], veh_org, actor)}


@router.get("/proposals", response_model=list[s.ProposalOut])
def list_proposals(shipment_id: uuid.UUID | None = None, status: str | None = None,
                   actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    now = _now()
    stmt = (select(m.Proposal).join(m.Shipment, m.Shipment.id == m.Proposal.shipment_id)
            .join(m.Vehicle, m.Vehicle.id == m.Proposal.vehicle_id)
            .outerjoin(m.Slot, m.Slot.id == m.Proposal.slot_id))
    if actor.role != "dispatcher":
        stmt = stmt.where(or_(m.Shipment.tenant_id == actor.org_id, m.Vehicle.tenant_id == actor.org_id,
                              m.Slot.node_org_id == actor.org_id))
    if shipment_id:
        stmt = stmt.where(m.Proposal.shipment_id == shipment_id)
    if status:
        stmt = stmt.where(m.Proposal.status == status)
    rows = session.execute(stmt.order_by(m.Proposal.created_at.desc(), m.Proposal.score.desc()).limit(200)).scalars().all()
    return proposal_views(session, actor, list(rows), now)


@router.get("/proposals/{proposal_id}", response_model=s.ProposalOut)
def get_proposal(proposal_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    now = _now()
    prop = session.get(m.Proposal, proposal_id)
    if prop is not None:
        orgs = bk.party_orgs(session.get(m.Shipment, prop.shipment_id), session.get(m.Vehicle, prop.vehicle_id),
                             session.get(m.Slot, prop.slot_id) if prop.slot_id else None)
        if bk.is_visible(actor, orgs):
            return proposal_view(session, actor, prop, now)
    raise HTTPException(status_code=404, detail="Proposal not found")


def _act(fn, proposal_id: uuid.UUID, body: s.ActionIn, key: str | None, actor: Actor, session: Session, response: Response):
    if not key or len(key) > 100:
        raise HTTPException(status_code=400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED",
                                                     "message": "Idempotency-Key header is required (<=100 chars)"})
    now = _now()
    try:
        prop, replay = fn(session, actor, proposal_id, body.version, key, now)
        session.commit()
    except bk.BookingError as e:
        session.commit() if e.commit else session.rollback()
        raise _http(e) from None
    except DBAPIError:  # deadlock/serialization: client có thể thử lại an toàn nhờ Idempotency-Key
        session.rollback()
        raise HTTPException(status_code=503, detail={"code": "RETRY", "message": "Transient database conflict, retry"}) from None
    if replay:
        response.headers["Idempotent-Replay"] = "true"
    return proposal_view(session, actor, prop, now)


@router.post("/proposals/{proposal_id}/hold", response_model=s.ProposalOut)
def hold(proposal_id: uuid.UUID, body: s.ActionIn, response: Response, idempotency_key: str | None = Header(default=None),
         actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    return _act(bk.hold, proposal_id, body, idempotency_key, actor, session, response)


@router.post("/proposals/{proposal_id}/accept", response_model=s.ProposalOut)
def accept(proposal_id: uuid.UUID, body: s.ActionIn, response: Response, idempotency_key: str | None = Header(default=None),
           actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    return _act(bk.accept, proposal_id, body, idempotency_key, actor, session, response)


@router.post("/proposals/{proposal_id}/reject", response_model=s.ProposalOut)
def reject(proposal_id: uuid.UUID, body: s.ActionIn, response: Response, idempotency_key: str | None = Header(default=None),
           actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    return _act(bk.reject, proposal_id, body, idempotency_key, actor, session, response)


@router.get("/proposals/{proposal_id}/timeline", response_model=s.TimelineOut)
def get_timeline(proposal_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    try:
        return audit.timeline(session, actor, proposal_id)
    except bk.BookingError as e:
        raise _http(e) from None


@router.get("/proposals/{proposal_id}/replay", response_model=s.ReplayOut)
def get_replay(proposal_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    try:
        return audit.replay(session, actor, proposal_id)
    except bk.BookingError as e:
        raise _http(e) from None
