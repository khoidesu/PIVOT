"""Kiểm tra quyền ở tầng ứng dụng (DRAFT 4.2): tenant + participant + vai trò; ẩn trường nhạy cảm.

Truy cập trái phép theo id trả 404 (không lộ sự tồn tại). RLS (nếu thêm) chỉ là lớp bổ sung.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import models as m
from .auth import Actor

# 12/11/2026 (BUG-02): chỉ chủ hàng tạo/sửa/huỷ lô; nhà vận tải quản lý xe, không tự tạo lô (thay quyết định "carrier = forwarder").
CAN_CREATE_SHIPMENT = {"shipper"}
CAN_EDIT_SHIPMENT = {"shipper"}


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


def price_visible_ids(session: Session, actor: Actor, shipments: list[m.Shipment]) -> set[uuid.UUID]:
    """Id các lô mà actor được xem giá + tên khách hàng: chủ lô, hoặc participant có can_see_price.

    Một truy vấn cho cả danh sách (tránh N+1). Điều phối viên không bao giờ được xem.
    """
    if actor.role == "dispatcher":
        return set()
    ids = {s.id for s in shipments if s.tenant_id == actor.org_id}
    others = [s.id for s in shipments if s.id not in ids]
    if others:
        ids |= set(session.execute(
            select(m.ShipmentParticipant.shipment_id).where(
                m.ShipmentParticipant.shipment_id.in_(others),
                m.ShipmentParticipant.org_id == actor.org_id,
                m.ShipmentParticipant.can_see_price.is_(True),
            )
        ).scalars())
    return ids


def visible_vehicles_stmt(actor: Actor):
    stmt = select(m.Vehicle)
    if actor.role == "dispatcher":
        return stmt
    return stmt.where(m.Vehicle.tenant_id == actor.org_id)
