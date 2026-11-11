import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import Actor, current_actor
from ..db import get_session
from ..sim import gps
from ..tracking import service as tracking

router = APIRouter(prefix="/v1")


@router.get("/tracking")
def list_tracking(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Chuyến đang theo dõi theo quyền (chủ lô / nhà vận tải / ICD / điều phối viên). Không có giá, khách hàng."""
    return tracking.list_trips(session, actor, datetime.now(timezone.utc))


@router.get("/tracking/{proposal_id}")
def tracking_detail(proposal_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    out = tracking.trip_detail(session, actor, proposal_id, datetime.now(timezone.utc))
    if out is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return out


@router.post("/tracking/{proposal_id}/road-route")
def fetch_road_route(proposal_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Lấy & lưu tuyến đường bộ thật (OSRM) cho chuyến đã cam kết nhưng chưa chạy. Idempotent; chuyến đang chạy giữ nguyên hình học.
    Ai thấy được chuyến thì gọi được (chỉ lưu dữ liệu bản đồ công khai, không tiết lộ gì thêm)."""
    for prop, _sh, _v, _sl in tracking._visible_proposals(session, actor, only_active=False):
        if prop.id == proposal_id:
            tr = tracking.ensure_road_route(session, prop)
            session.commit()
            return {"route_source": "osrm" if tr else "simulated",
                    "distance_km": tr.distance_km if tr else None, "duration_min": tr.duration_min if tr else None}
    raise HTTPException(status_code=404, detail="Trip not found")


class SimIn(BaseModel):
    mode: str = "normal"


def _sim_guard(actor: Actor, session: Session, proposal_id: uuid.UUID):
    """Nhà vận tải của chuyến hoặc điều phối viên mới điều khiển được bộ giả lập."""
    from .. import models as m
    from ..config import settings
    if settings.data_mode != "mock":
        raise HTTPException(status_code=403, detail="Only available for simulated (mock) data")
    prop = session.get(m.Proposal, proposal_id)
    veh = session.get(m.Vehicle, prop.vehicle_id) if prop else None
    if prop is None or not (actor.role == "dispatcher" or (actor.role == "carrier" and veh.tenant_id == actor.org_id)):
        raise HTTPException(status_code=404, detail="Trip not found")


@router.post("/sim/{proposal_id}/start")
def sim_start(proposal_id: uuid.UUID, speedup: float = 20.0, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    _sim_guard(actor, session, proposal_id)
    try:
        sim = gps.start(session, proposal_id, datetime.now(timezone.utc), time_scale=max(1.0, min(speedup, 20000.0)))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    session.commit()
    return {"running": sim.running, "mode": sim.mode, "is_simulated": True}


@router.post("/sim/{proposal_id}/mode")
def sim_mode(proposal_id: uuid.UUID, body: SimIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    _sim_guard(actor, session, proposal_id)
    try:
        sim = gps.set_mode(session, proposal_id, body.mode)
        gps.report_mode_incident(session, proposal_id, datetime.now(timezone.utc))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    session.commit()
    return {"running": sim.running, "mode": sim.mode, "is_simulated": True}


@router.post("/sim/tick")
def sim_tick(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    if actor.role not in ("dispatcher", "carrier"):
        raise HTTPException(status_code=403, detail="Not allowed")
    n = gps.tick(session, datetime.now(timezone.utc))
    session.commit()
    return {"positions_sent": n}
