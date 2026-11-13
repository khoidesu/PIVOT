import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from ..access import (
    CAN_CREATE_SHIPMENT, get_visible_shipment, price_visible_ids, visible_shipments_stmt,
    visible_vehicles_stmt,
)
from .. import fleet, nodes, shipment_ops
from ..admin import require_admin
from ..assumptions import get_active
from ..booking.service import BookingError
from ..auth import Actor, current_actor
from ..config import settings
from ..db import get_session

router = APIRouter(prefix="/v1")

REQUIRED = ("cargo_type", "weight_kg", "volume_m3", "pickup_deadline", "cutoff_at")


def _shipment_out(ship: m.Shipment, show_sensitive: bool) -> s.ShipmentOut:
    out = s.ShipmentOut.model_validate(ship)
    if not show_sensitive:
        out.price_vnd = None
        out.customer_name = None
    out.missing_fields = [f for f in REQUIRED if getattr(ship, f) is None]
    return out


def shipment_out_many(session: Session, actor: Actor, ships: list[m.Shipment]) -> list[s.ShipmentOut]:
    visible = price_visible_ids(session, actor, ships)
    # Tên tổ chức sở hữu lô (chỉ tên; lô đã hiển thị với người xem) — để phân biệt lô trùng mã giữa các chủ hàng (QA-10).
    tids = {x.tenant_id for x in ships}
    names = dict(session.execute(select(m.Organization.id, m.Organization.name).where(m.Organization.id.in_(tids))).all()) if tids else {}
    out = []
    for x in ships:
        o = _shipment_out(x, x.id in visible)
        o.tenant_name = names.get(x.tenant_id)
        out.append(o)
    return out


def _extractor_kind() -> str:
    """Bộ trích xuất nhập liệu đang chạy thật (theo cấu hình + có khoá). Không lộ khoá."""
    mode = settings.intake_extractor
    if mode == "llm" and settings.anthropic_api_key:
        return "llm"
    if mode == "hybrid" and settings.gemini_api_key:
        return "hybrid"
    return "rule"


@router.get("/me", response_model=s.MeOut)
def me(actor: Actor = Depends(current_actor)):
    return s.MeOut(user_id=actor.user_id, user_name=actor.user_name, org_id=actor.org_id,
                   org_name=actor.org_name, org_type=actor.org_type, role=actor.role)


@router.get("/meta", response_model=s.MetaOut)
def meta(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    params = get_active(session).params
    return s.MetaOut(data_mode=settings.data_mode, is_simulated=True,
                     server_time=datetime.now(timezone.utc),
                     stale_position_minutes=params["stale_position_minutes"],
                     stale_shipment_minutes=params["stale_shipment_minutes"],
                     admin_key_required=bool(settings.admin_key),
                     image_intake_enabled=bool(settings.gemini_api_key and settings.intake_image_enabled),
                     pdf_intake_enabled=settings.intake_pdf_enabled,
                     extractor_kind=_extractor_kind())


@router.post("/demo/retime", dependencies=[Depends(require_admin)])
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
    return shipment_out_many(session, actor, list(rows))


@router.get("/shipments/{shipment_id}", response_model=s.ShipmentOut)
def get_shipment(shipment_id: uuid.UUID, actor: Actor = Depends(current_actor),
                 session: Session = Depends(get_session)):
    return shipment_out_many(session, actor, [get_visible_shipment(session, actor, shipment_id)])[0]


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
    fields = body.model_dump(exclude={"draft_id"})
    draft_ev = None
    if body.draft_id is not None:  # tạo từ bản nháp nhập liệu: bản nháp phải do chính tổ chức này tạo
        draft_ev = session.execute(select(m.Event).where(
            m.Event.entity_type == "intake_draft", m.Event.entity_id == body.draft_id, m.Event.tenant_id == actor.org_id)).scalar_one_or_none()
        if draft_ev is None:
            raise HTTPException(status_code=422, detail="draft_id does not exist")
    ship = m.Shipment(tenant_id=actor.org_id, status="open", is_simulated=True, **fields)
    session.add(ship)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Shipment code already exists") from None
    session.add(m.ShipmentParticipant(shipment_id=ship.id, org_id=actor.org_id, role=actor.role,
                                      can_see_price=True))
    if draft_ev is not None:  # ghi nhận người duyệt + những trường còn cần xem lại của bản nháp
        now = datetime.now(timezone.utc)
        session.add(m.Event(tenant_id=actor.org_id, entity_type="shipment", entity_id=ship.id, event_type="SHIPMENT_CREATED_FROM_DRAFT",
                            occurred_at=now, received_at=now, source_system="pivot.intake", source_event_id=f"created:{ship.id}",
                            payload={"draft_id": str(body.draft_id), "reviewed_by": str(actor.user_id),
                                     "draft_needs_review": draft_ev.payload.get("needs_review", [])},
                            correlation_id=str(actor.user_id)))
    session.commit()
    return shipment_out_many(session, actor, [ship])[0]


def _ops_http(e: BookingError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message, "reasons": []})


@router.patch("/shipments/{shipment_id}", response_model=s.ShipmentOut)
def update_shipment(shipment_id: uuid.UUID, body: s.ShipmentUpdate, actor: Actor = Depends(current_actor),
                    session: Session = Depends(get_session)):
    """Sửa yêu cầu (chủ lô, khi còn open và chưa có đề xuất giữ/cam kết). Khoá lạc quan bằng `version`."""
    changes = body.model_dump(exclude={"version"}, exclude_none=True)
    try:
        ship = shipment_ops.update(session, actor, shipment_id, changes, body.version, datetime.now(timezone.utc))
        session.commit()
    except BookingError as e:
        session.rollback()
        raise _ops_http(e) from None
    return shipment_out_many(session, actor, [ship])[0]


@router.post("/shipments/{shipment_id}/refresh", response_model=s.ShipmentOut)
def refresh_shipment(shipment_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Chủ lô xác nhận dữ liệu lô còn đúng → làm mới tuổi dữ liệu (không đổi nội dung)."""
    try:
        ship = shipment_ops.refresh(session, actor, shipment_id, datetime.now(timezone.utc))
        session.commit()
    except BookingError as e:
        session.rollback()
        raise _ops_http(e) from None
    return shipment_out_many(session, actor, [ship])[0]


@router.delete("/shipments/{shipment_id}", response_model=s.ShipmentOut)
def cancel_shipment(shipment_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Huỷ yêu cầu (xoá mềm: giữ vết audit). Không huỷ được khi đã có đề xuất đang giữ/đã cam kết."""
    try:
        ship = shipment_ops.cancel(session, actor, shipment_id, datetime.now(timezone.utc))
        session.commit()
    except BookingError as e:
        session.rollback()
        raise _ops_http(e) from None
    return shipment_out_many(session, actor, [ship])[0]


@router.get("/vehicles", response_model=list[s.VehicleOut])
def list_vehicles(to_location_id: uuid.UUID | None = None, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Xe (của tổ chức mình; điều phối viên xem tất cả) kèm bãi đang đậu + trạng thái. `to_location_id` (địa điểm công khai, vd điểm lấy hàng)
    → thêm khoảng cách ước tính + ETA từ bãi tới đó."""
    target = None
    if to_location_id is not None:
        target = session.get(m.Location, to_location_id)
        if target is None:
            raise HTTPException(status_code=422, detail="Unknown to_location_id")
    vehicles = session.execute(visible_vehicles_stmt(actor).order_by(m.Vehicle.plate)).scalars().all()
    return fleet.vehicle_views(session, list(vehicles), datetime.now(timezone.utc), target)


@router.post("/slots/refresh")
def refresh_slots(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """ICD kéo dài lịch slot MÔ PHỎNG của chính mình tới `slot_horizon_hours` (idempotent). Slot thật không bao giờ bị sinh; không nới hard gate."""
    if actor.role != "node_operator":
        raise HTTPException(status_code=403, detail="Terminal operator only")
    out = nodes.refresh_slots(session, actor.org_id, datetime.now(timezone.utc))
    session.commit()
    return {**out, "is_simulated": True}


@router.post("/vehicles/refresh-fleet")
def refresh_fleet(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Nhà vận tải làm tươi vị trí + khung rảnh của xe đang rảnh (đường sự kiện thật, idempotent theo phút). Gọi khi đăng nhập và định kỳ."""
    if actor.role != "carrier":
        raise HTTPException(status_code=403, detail="Carrier only")
    out = fleet.refresh_fleet(session, actor, datetime.now(timezone.utc))
    session.commit()
    return out


@router.get("/slots", response_model=list[s.SlotOut])
def list_slots(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """ICD (node_operator) chỉ thấy slot của tổ chức mình (QA-06); chủ hàng/nhà vận tải/điều phối viên thấy mọi ICD kèm tên.
    Bộ ghép đọc slot trực tiếp trong DB nên không phụ thuộc endpoint này."""
    names = dict(session.execute(select(m.Organization.id, m.Organization.name).where(m.Organization.org_type == "node")).all())
    stmt = select(m.Slot).order_by(m.Slot.start_at)
    if actor.role == "node_operator":
        stmt = stmt.where(m.Slot.node_org_id == actor.org_id)
    return [s.SlotOut.model_validate(x).model_copy(update={"node_org_name": names.get(x.node_org_id)})
            for x in session.execute(stmt).scalars().all()]
