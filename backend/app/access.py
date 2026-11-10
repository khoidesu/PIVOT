"""Kiểm tra quyền ở tầng ứng dụng (DRAFT 4.2): tenant + participant + vai trò; ẩn trường nhạy cảm.

Truy cập trái phép theo id trả 404 (không lộ sự tồn tại). RLS (nếu thêm) chỉ là lớp bổ sung.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import models as m
from .auth import Actor

CAN_CREATE_SHIPMENT = {"shipper", "carrier"}


def _participant_ids(actor: Actor):
    return select(m.ShipmentParticipant.shipment_id).where(m.ShipmentParticipant.org_id == actor.org_id)


def visible_shipments_stmt(actor: Actor):
    stmt = select(m.Shipment)
    if actor.role == "dispatcher":  # điều phối viên xem metadata mọi lô, KHÔNG xem giá/khách hàng
        return stmt
    return stmt.where(or_(m.Shipment.tenant_id == actor.org_id, m.Shipment.id.in_(_participant_ids(actor))))


def get_visible_shipment(session: Session, actor: Actor, shipment_id: uuid.UUID) -> m.Shipment:
    ship = session.execute(visible_shipments_stmt(actor).where(m.Shipment.id == shipment_id)).scalar_one_or_none()
    if ship is None:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return ship


def can_see_sensitive(session: Session, actor: Actor, shipment: m.Shipment) -> bool:
    """Giá + tên khách hàng: chủ lô, hoặc participant được cấp can_see_price."""
    if shipment.tenant_id == actor.org_id:
        return True
    part = session.execute(
        select(m.ShipmentParticipant).where(
            m.ShipmentParticipant.shipment_id == shipment.id,
            m.ShipmentParticipant.org_id == actor.org_id,
        )
    ).scalar_one_or_none()
    return bool(part and part.can_see_price)


def visible_vehicles_stmt(actor: Actor):
    stmt = select(m.Vehicle)
    if actor.role == "dispatcher":
        return stmt
    return stmt.where(m.Vehicle.tenant_id == actor.org_id)
