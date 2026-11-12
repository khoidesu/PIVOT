"""Sửa / huỷ yêu cầu vận chuyển.

- Chỉ CHỦ LÔ (shipper/carrier của tổ chức sở hữu) được sửa/huỷ; điều phối viên và bên khác thì không.
- Chỉ khi lô còn `open` và KHÔNG có đề xuất đang giữ/đã cam kết (pending_acceptance|confirmed|executing) → 409 SHIPMENT_LOCKED.
  Đã cam kết thì phải đi qua luồng ngoại lệ, không được sửa lặng lẽ (DRAFT 5.4).
- Sửa dùng khoá lạc quan `version`. Sửa xong: version+1, data_updated_at=now (dữ liệu "tươi" lại), các đề xuất `proposed`
  của lô bị `cancelled` vì đầu vào đã đổi (phải ghép lại).
- "Xoá" = HUỶ (status `cancelled`): sự kiện/đề xuất/sổ lợi ích tham chiếu lô nên không xoá cứng, để giữ vết audit (DRAFT mục 10).
- `refresh`: chủ lô xác nhận dữ liệu còn đúng (làm mới tuổi dữ liệu, không đổi nội dung).
- Mọi thay đổi ghi sự kiện SHIPMENT_UPDATED / SHIPMENT_CANCELLED / SHIPMENT_REFRESHED (chỉ tên trường, không ghi giá/khách hàng).
"""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .access import CAN_EDIT_SHIPMENT
from .auth import Actor
from .booking.service import BookingError

EDITABLE = ("cargo_type", "weight_kg", "volume_m3", "origin_location_id", "dest_location_id", "ready_at",
            "pickup_deadline", "cutoff_at", "price_vnd", "customer_name")
LOCKING = ("pending_acceptance", "confirmed", "executing")
SENSITIVE = {"price_vnd", "customer_name"}


def _lock(session: Session, actor: Actor, shipment_id: uuid.UUID,
          roles: frozenset = frozenset(CAN_EDIT_SHIPMENT)) -> tuple[m.Shipment, list[m.Proposal]]:
    # thứ tự khoá cố định proposal → shipment (cùng thứ tự với hold/accept) để không deadlock với giữ chỗ song song
    props = session.execute(select(m.Proposal).where(m.Proposal.shipment_id == shipment_id)
                            .order_by(m.Proposal.id).with_for_update()).scalars().all()
    ship = session.execute(select(m.Shipment).where(m.Shipment.id == shipment_id).with_for_update()).scalar_one_or_none()
    if ship is None or ship.tenant_id != actor.org_id and actor.role != "dispatcher":
        raise BookingError("NOT_FOUND", "Shipment not found", 404)
    if actor.role not in roles or ship.tenant_id != actor.org_id:
        raise BookingError("FORBIDDEN", "Only the owner can modify a shipment", 403)
    return ship, props


def _ensure_unlocked(ship: m.Shipment, props: list[m.Proposal], now: datetime) -> None:
    if ship.status != "open":
        raise BookingError("SHIPMENT_LOCKED", f"Shipment is '{ship.status}' and cannot be modified", 409)
    for p in props:
        live = p.status in LOCKING and not (p.status == "pending_acceptance" and p.expires_at and p.expires_at < now)
        if live:
            raise BookingError("SHIPMENT_LOCKED", "A proposal is held or committed for this shipment; resolve it first", 409)


def _invalidate_open_proposals(props: list[m.Proposal]) -> int:
    n = 0
    for p in props:
        if p.status == "proposed":
            p.status = "cancelled"
            p.version += 1
            n += 1
    return n


def _audit(session: Session, actor: Actor, ship: m.Shipment, etype: str, payload: dict, now: datetime) -> None:
    session.add(m.Event(tenant_id=actor.org_id, entity_type="shipment", entity_id=ship.id, event_type=etype,
                        occurred_at=now, received_at=now, source_system="pivot.shipments", source_event_id=str(uuid.uuid4()),
                        payload=payload, correlation_id=str(actor.user_id)))


def update(session: Session, actor: Actor, shipment_id: uuid.UUID, changes: dict, version: int, now: datetime) -> m.Shipment:
    ship, props = _lock(session, actor, shipment_id)
    if ship.version != version:
        raise BookingError("VERSION_CONFLICT", f"Shipment version is {ship.version}, got {version}", 409)
    _ensure_unlocked(ship, props, now)
    changed = {k: v for k, v in changes.items() if k in EDITABLE and v is not None}
    if not changed:
        raise BookingError("VALIDATION", "No editable field provided", 422)
    for k in ("origin_location_id", "dest_location_id"):
        if k in changed and session.get(m.Location, changed[k]) is None:
            raise BookingError("VALIDATION", f"{k} does not exist", 422)
    merged = {k: changed.get(k, getattr(ship, k)) for k in ("ready_at", "pickup_deadline", "cutoff_at")}
    if None in merged.values() or not (merged["ready_at"] < merged["pickup_deadline"] < merged["cutoff_at"]):
        raise BookingError("VALIDATION", "require ready_at < pickup_deadline < cutoff_at", 422)
    for k, v in changed.items():
        setattr(ship, k, v)
    ship.version += 1
    ship.data_updated_at = now  # dữ liệu lô được làm mới
    cancelled = _invalidate_open_proposals(props)
    _audit(session, actor, ship, "SHIPMENT_UPDATED",
           {"fields": sorted(changed), "sensitive_fields_changed": sorted(SENSITIVE & set(changed)),
            "version": ship.version, "proposals_invalidated": cancelled}, now)
    session.flush()
    return ship


def refresh(session: Session, actor: Actor, shipment_id: uuid.UUID, now: datetime) -> m.Shipment:
    """Chủ lô xác nhận dữ liệu lô VẪN ĐÚNG → làm mới `data_updated_at` (để qua cổng shipment_fresh).

    Không đổi nội dung, không tăng version, không vô hiệu đề xuất (không có đầu vào nào đổi). Có ghi audit
    SHIPMENT_REFRESHED để thấy ai xác nhận lúc nào; vẫn bị khoá khi lô đã giữ/cam kết.
    """
    ship, props = _lock(session, actor, shipment_id, roles=frozenset({"shipper", "carrier"}))
    _ensure_unlocked(ship, props, now)
    ship.data_updated_at = now
    _audit(session, actor, ship, "SHIPMENT_REFRESHED", {"version": ship.version}, now)
    session.flush()
    return ship


def cancel(session: Session, actor: Actor, shipment_id: uuid.UUID, now: datetime) -> m.Shipment:
    ship, props = _lock(session, actor, shipment_id)
    if ship.status == "cancelled":
        return ship  # idempotent
    _ensure_unlocked(ship, props, now)
    ship.status = "cancelled"
    ship.version += 1
    cancelled = _invalidate_open_proposals(props)
    _audit(session, actor, ship, "SHIPMENT_CANCELLED", {"version": ship.version, "proposals_invalidated": cancelled}, now)
    session.flush()
    return ship
