import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from ..access import (
    CAN_CREATE_SHIPMENT, can_see_sensitive, get_visible_shipment, visible_shipments_stmt,
    visible_vehicles_stmt,
)
from ..auth import Actor, current_actor
from ..config import settings
from ..db import get_session

router = APIRouter(prefix="/v1")

REQUIRED = ("cargo_type", "weight_kg", "volume_m3", "pickup_deadline", "cutoff_at")


def _active_assumptions(session: Session) -> m.AssumptionSet:
    return session.execute(select(m.AssumptionSet).order_by(m.AssumptionSet.created_at.desc())).scalars().first()


def _shipment_out(session: Session, actor: Actor, ship: m.Shipment) -> s.ShipmentOut:
    out = s.ShipmentOut.model_validate(ship)
    if not can_see_sensitive(session, actor, ship):
        out.price_vnd = None
        out.customer_name = None
    out.missing_fields = [f for f in REQUIRED if getattr(ship, f) is None]
    return out


@router.get("/me", response_model=s.MeOut)
def me(actor: Actor = Depends(current_actor)):
    return s.MeOut(user_id=actor.user_id, user_name=actor.user_name, org_id=actor.org_id,
                   org_name=actor.org_name, org_type=actor.org_type, role=actor.role)


@router.get("/meta", response_model=s.MetaOut)
def meta(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    params = _active_assumptions(session).params
    return s.MetaOut(data_mode=settings.data_mode, is_simulated=True,
                     server_time=datetime.now(timezone.utc),
                     stale_position_minutes=params["stale_position_minutes"])


@router.post("/demo/retime")
def demo_retime(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Đưa dữ liệu MÔ PHỎNG về trạng thái tươi trước mỗi kịch bản demo. Chỉ điều phối viên, chỉ khi mock."""
    from ..seed import retime

    if settings.data_mode != "mock":
        raise HTTPException(status_code=403, detail="Only available for simulated (mock) data")
    if actor.role != "dispatcher":
        raise HTTPException(status_code=403, detail="Dispatcher only")
    delta = retime(session)
    session.commit()
    return {"retimed_by_seconds": int(delta.total_seconds()), "is_simulated": True}


@router.get("/locations", response_model=list[s.LocationOut])
def locations(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    return session.execute(select(m.Location).order_by(m.Location.name)).scalars().all()


@router.get("/shipments", response_model=list[s.ShipmentOut])
def list_shipments(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    rows = session.execute(visible_shipments_stmt(actor).order_by(m.Shipment.code)).scalars().all()
    return [_shipment_out(session, actor, r) for r in rows]


@router.get("/shipments/{shipment_id}", response_model=s.ShipmentOut)
def get_shipment(shipment_id: uuid.UUID, actor: Actor = Depends(current_actor),
                 session: Session = Depends(get_session)):
    return _shipment_out(session, actor, get_visible_shipment(session, actor, shipment_id))


@router.post("/shipments", response_model=s.ShipmentOut, status_code=201)
def create_shipment(body: s.ShipmentCreate, actor: Actor = Depends(current_actor),
                    session: Session = Depends(get_session)):
    if actor.role not in CAN_CREATE_SHIPMENT:
        raise HTTPException(status_code=403, detail="Role cannot create shipments")
    known = set(session.execute(
        select(m.Location.id).where(m.Location.id.in_([body.origin_location_id, body.dest_location_id]))
    ).scalars())
    for field in ("origin_location_id", "dest_location_id"):
        if getattr(body, field) not in known:
            raise HTTPException(status_code=422, detail=f"{field} does not exist")
    # mã lô chỉ unique TRONG tenant → không lộ lô của tổ chức khác qua lỗi trùng mã
    ship = m.Shipment(tenant_id=actor.org_id, status="open", is_simulated=True, **body.model_dump())
    session.add(ship)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Shipment code already exists") from None
    session.add(m.ShipmentParticipant(shipment_id=ship.id, org_id=actor.org_id, role=actor.role,
                                      can_see_price=True))
    session.commit()
    return _shipment_out(session, actor, ship)


@router.get("/vehicles", response_model=list[s.VehicleOut])
def list_vehicles(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    return session.execute(visible_vehicles_stmt(actor).order_by(m.Vehicle.plate)).scalars().all()


@router.get("/slots", response_model=list[s.SlotOut])
def list_slots(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    return session.execute(select(m.Slot).order_by(m.Slot.start_at)).scalars().all()
