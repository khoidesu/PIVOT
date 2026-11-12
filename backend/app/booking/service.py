"""Booking = state machine có transaction (DRAFT 5.4).

Proposal:    proposed → pending_acceptance → confirmed → executing → completed   (+ rejected | expired | cancelled)
Reservation: held → committed  |  released | expired

Nguyên tắc cài đặt:
- Thứ tự khoá cố định: proposal → shipment → vehicle → slot (SELECT … FOR UPDATE) để không deadlock.
- Hold hết hạn được đánh dấu `expired` NGAY TRONG transaction (expire_stale) trước mọi kiểm tra — vì partial unique index
  không thể tham chiếu now(), hold chưa dọn sẽ chiếm tài nguyên.
- Mọi chuyển trạng thái re-check hard gate với dữ liệu hiện tại trong cùng transaction (DRAFT: "kiểm tra lại").
- Slot nhiều chỗ: `UPDATE … SET remaining = remaining - 1 WHERE remaining > 0` nguyên tử (+ CHECK 0..capacity).
- Quyền xác nhận thuộc chủ thể: carrier nhận việc, shipper duyệt lô, node duyệt slot. Điều phối viên KHÔNG accept.
- Idempotency-Key theo tổ chức: gửi lại cùng key → trả kết quả cũ, không tác động lần hai.
- Đổi trạng thái + ghi outbox trong cùng transaction. Không gọi API ngoài trong transaction.
"""
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from ..assumptions import get_active
from ..auth import Actor
from ..matching import gates

OPEN_STATES = ("proposed", "pending_acceptance")
PARTIES = ("shipper", "carrier", "node")


class BookingError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, reasons: list | None = None, commit: bool = False):
        super().__init__(message)
        self.code, self.message, self.status, self.reasons, self.commit = code, message, status, reasons or [], commit


# ---------- tải & khoá ----------
def lock_proposal(session: Session, proposal_id: uuid.UUID) -> m.Proposal:
    prop = session.execute(select(m.Proposal).where(m.Proposal.id == proposal_id).with_for_update()).scalar_one_or_none()
    if prop is None:
        raise BookingError("NOT_FOUND", "Proposal not found", 404)
    return prop


def lock_resources(session: Session, prop: m.Proposal):
    ship = session.execute(select(m.Shipment).where(m.Shipment.id == prop.shipment_id).with_for_update()).scalar_one()
    veh = session.execute(select(m.Vehicle).where(m.Vehicle.id == prop.vehicle_id).with_for_update()).scalar_one()
    slot = None
    if prop.slot_id:
        slot = session.execute(select(m.Slot).where(m.Slot.id == prop.slot_id).with_for_update()).scalar_one()
    return ship, veh, slot


def party_orgs(ship: m.Shipment, veh: m.Vehicle, slot: m.Slot | None) -> dict[str, uuid.UUID]:
    orgs = {"shipper": ship.tenant_id, "carrier": veh.tenant_id}
    if slot is not None:
        orgs["node"] = slot.node_org_id
    return orgs


def actor_parties(actor: Actor, orgs: dict[str, uuid.UUID]) -> set[str]:
    """Bên mà actor được xác nhận thay mặt (DRAFT mục 7). Điều phối viên không có quyền accept."""
    found = set()
    if actor.role == "carrier" and orgs.get("carrier") == actor.org_id:
        found.add("carrier")
    if actor.role in ("shipper", "carrier") and orgs.get("shipper") == actor.org_id:  # forwarder sở hữu lô
        found.add("shipper")
    if actor.role == "node_operator" and orgs.get("node") == actor.org_id:
        found.add("node")
    return found


def can_hold(actor: Actor, orgs: dict[str, uuid.UUID]) -> bool:
    return actor.role == "dispatcher" or (
        actor.role in ("shipper", "carrier") and orgs.get("shipper") == actor.org_id)


def is_visible(actor: Actor, orgs: dict[str, uuid.UUID]) -> bool:
    return actor.role == "dispatcher" or actor.org_id in orgs.values()


def accepted_parties(session: Session, proposal_id: uuid.UUID) -> set[str]:
    rows = session.execute(select(m.Decision.party).where(
        m.Decision.proposal_id == proposal_id, m.Decision.action == "accept")).scalars()
    return {p for p in rows if p}


def latest_window(session: Session, vehicle_id: uuid.UUID) -> m.AvailabilityWindow | None:
    return session.execute(select(m.AvailabilityWindow).where(m.AvailabilityWindow.vehicle_id == vehicle_id)
                           .order_by(m.AvailabilityWindow.free_from.desc())).scalars().first()


# ---------- idempotency ----------
def find_replay(session: Session, actor: Actor, key: str, proposal_id: uuid.UUID, action: str):
    dec = session.execute(select(m.Decision).where(
        m.Decision.actor_org_id == actor.org_id, m.Decision.idempotency_key == key)).scalar_one_or_none()
    if dec is None:
        return None
    if dec.proposal_id != proposal_id or dec.action != action:
        raise BookingError("IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was used for a different request", 422)
    return dec


# ---------- hết hạn & giải phóng ----------
def _restore_slot(session: Session, slot_id: uuid.UUID) -> None:
    session.execute(update(m.Slot).where(m.Slot.id == slot_id)
                    .values(remaining=m.Slot.remaining + 1, version=m.Slot.version + 1))


def release_holds(session: Session, proposal_id: uuid.UUID, to_status: str) -> None:
    rows = session.execute(select(m.Reservation).where(
        m.Reservation.proposal_id == proposal_id, m.Reservation.status == "held").with_for_update()).scalars().all()
    for r in rows:
        r.status = to_status
        if r.resource_type == "slot":
            _restore_slot(session, r.resource_id)


def expire_stale(session: Session, now: datetime) -> list[uuid.UUID]:
    """Đánh dấu hold/đề xuất quá hạn là expired (trong transaction hiện tại) và trả slot về."""
    # ORDER BY id: nhiều giao dịch cùng dọn một lúc khoá các dòng theo CÙNG thứ tự → giảm nguy cơ bế tắc (deadlock)
    stale = session.execute(select(m.Reservation).where(
        m.Reservation.status == "held", m.Reservation.expires_at < now).order_by(m.Reservation.id).with_for_update()).scalars().all()
    for r in stale:
        r.status = "expired"
        if r.resource_type == "slot":
            _restore_slot(session, r.resource_id)
    props = session.execute(select(m.Proposal).where(
        m.Proposal.status.in_(OPEN_STATES), m.Proposal.expires_at < now).order_by(m.Proposal.id).with_for_update()).scalars().all()
    for p in props:
        p.status = "expired"
        p.version += 1
    return [p.id for p in props]


def reset_open_commitments(session: Session, now: datetime) -> None:
    """Dùng khi retime demo: đề xuất/hold đang mở được expire sạch thay vì bị lệch thời gian."""
    for prop in session.execute(select(m.Proposal).where(m.Proposal.status.in_(OPEN_STATES)).with_for_update()).scalars():
        release_holds(session, prop.id, "expired")
        prop.status = "expired"
        prop.version += 1


# ---------- re-check hard gate ----------
def gate_to_dict(r: gates.GateResult) -> dict:
    return {"gate": r.gate, "status": r.status, "reason_code": r.reason_code, "detail": r.detail}


def recheck(session: Session, prop: m.Proposal, ship, veh, slot, now: datetime, own_hold: bool) -> list[dict]:
    """Trả danh sách lý do KHÔNG đạt (rỗng = đạt). own_hold: slot đã bị chính proposal này giữ 1 chỗ."""
    params = get_active(session).params
    others_active = lambda rtype, rid: session.execute(select(m.Reservation.id).where(  # noqa: E731
        m.Reservation.resource_type == rtype, m.Reservation.resource_id == rid,
        m.Reservation.status.in_(("held", "committed")), m.Reservation.proposal_id != prop.id)).first() is not None
    slot_view = slot
    if slot is not None and own_hold:
        slot_view = SimpleNamespace(**{c.name: getattr(slot, c.name) for c in m.Slot.__table__.columns})
        slot_view.remaining = slot.remaining + 1
    verdict = gates.evaluate(ship, veh, latest_window(session, veh.id), slot_view, now, params,
                             vehicle_reserved=others_active("vehicle", veh.id))
    reasons = [gate_to_dict(r) for r in verdict.rejections]
    if ship.status != "open" or others_active("shipment", ship.id):
        reasons.append({"gate": "shipment_open", "status": "FAIL", "reason_code": "SHIPMENT_NOT_OPEN",
                        "detail": {"status": ship.status}})
    return reasons


# ---------- hành động ----------
def _record(session: Session, actor: Actor, prop: m.Proposal, action: str, party: str | None, key: str | None) -> None:
    session.add(m.Decision(proposal_id=prop.id, actor_user_id=actor.user_id, actor_org_id=actor.org_id,
                           action=action, party=party, proposal_version=prop.version, idempotency_key=key))


def _require_open(prop: m.Proposal, expected: str) -> None:
    if prop.status == "expired":
        raise BookingError("PROPOSAL_EXPIRED", "Proposal or hold has expired", 409)
    if prop.status != expected:
        raise BookingError("INVALID_STATE", f"Proposal is '{prop.status}', expected '{expected}'", 409)


def hold(session: Session, actor: Actor, proposal_id: uuid.UUID, version: int, key: str, now: datetime) -> tuple[m.Proposal, bool]:
    """proposed → pending_acceptance; tạo reservation held (xe, lô, slot) có hạn. Trả (proposal, is_replay)."""
    if (dec := find_replay(session, actor, key, proposal_id, "hold")):
        return session.get(m.Proposal, dec.proposal_id), True
    expire_stale(session, now)
    prop = lock_proposal(session, proposal_id)
    ship, veh, slot = lock_resources(session, prop)
    orgs = party_orgs(ship, veh, slot)
    if not is_visible(actor, orgs):
        raise BookingError("NOT_FOUND", "Proposal not found", 404)
    if not can_hold(actor, orgs):
        raise BookingError("FORBIDDEN", "Only the shipment owner or a dispatcher can hold", 403)
    if (dec := find_replay(session, actor, key, proposal_id, "hold")):  # request song song cùng key
        return prop, True
    if prop.version != version:
        raise BookingError("VERSION_CONFLICT", f"Proposal version is {prop.version}, got {version}", 409)
    _require_open(prop, "proposed")
    if slot is None:
        raise BookingError("SLOT_REQUIRED", "Proposal has no slot to hold", 409)

    reasons = recheck(session, prop, ship, veh, slot, now, own_hold=False)
    if reasons:
        raise BookingError("RECHECK_FAILED", "Resources are no longer feasible", 409, reasons)

    took = session.execute(update(m.Slot).where(m.Slot.id == slot.id, m.Slot.remaining > 0)
                           .values(remaining=m.Slot.remaining - 1, version=m.Slot.version + 1)
                           .returning(m.Slot.remaining)).first()
    if took is None:
        raise BookingError("SLOT_FULL", "No capacity left in slot", 409)
    expires = now + timedelta(seconds=get_active(session).params["hold_seconds"])
    try:
        with session.begin_nested():
            for rtype, rid in (("shipment", ship.id), ("vehicle", veh.id), ("slot", slot.id)):
                session.add(m.Reservation(proposal_id=prop.id, resource_type=rtype, resource_id=rid,
                                          status="held", expires_at=expires))
            session.flush()
    except IntegrityError:  # backstop của partial unique index: người thua cuộc trong race
        raise BookingError("RESOURCE_HELD", "Vehicle or shipment is already held by another proposal", 409) from None
    prop.status, prop.expires_at = "pending_acceptance", expires
    prop.version += 1
    _record(session, actor, prop, "hold", None, key)
    session.flush()
    return prop, False


def accept(session: Session, actor: Actor, proposal_id: uuid.UUID, version: int, key: str, now: datetime) -> tuple[m.Proposal, bool]:
    """Mỗi bên (carrier/shipper/node) xác nhận phần của mình; đủ 3 bên + re-check đạt → confirmed."""
    if (dec := find_replay(session, actor, key, proposal_id, "accept")):
        return session.get(m.Proposal, dec.proposal_id), True
    expire_stale(session, now)
    prop = lock_proposal(session, proposal_id)
    ship, veh, slot = lock_resources(session, prop)
    orgs = party_orgs(ship, veh, slot)
    if not is_visible(actor, orgs):
        raise BookingError("NOT_FOUND", "Proposal not found", 404)
    mine = actor_parties(actor, orgs)
    if not mine:
        raise BookingError("FORBIDDEN", "Your organization/role cannot accept this proposal", 403)
    if (dec := find_replay(session, actor, key, proposal_id, "accept")):
        return prop, True
    if prop.version != version:
        raise BookingError("VERSION_CONFLICT", f"Proposal version is {prop.version}, got {version}", 409)
    _require_open(prop, "pending_acceptance")

    done = accepted_parties(session, prop.id)
    new = sorted(mine - done)
    if not new:
        raise BookingError("ALREADY_ACCEPTED", "Your party already accepted this proposal", 409)
    for i, party in enumerate(new):
        _record(session, actor, prop, "accept", party, key if i == 0 else None)
    session.flush()

    if done | set(new) >= set(PARTIES):
        reasons = recheck(session, prop, ship, veh, slot, now, own_hold=True)
        if reasons:  # re-check thất bại: giải phóng toàn bộ, không xác nhận
            release_holds(session, prop.id, "released")
            prop.status = "cancelled"
            prop.version += 1
            raise BookingError("RECHECK_FAILED", "Re-check failed at final confirmation; holds released", 409,
                               reasons, commit=True)
        for r in session.execute(select(m.Reservation).where(
                m.Reservation.proposal_id == prop.id, m.Reservation.status == "held").with_for_update()).scalars():
            r.status = "committed"
        veh.status, ship.status = "committed", "matched"
        ship.version += 1
        # Một lô chỉ có một cam kết: các đề xuất còn mở của cùng lô không còn hiệu lực
        for sib in session.execute(select(m.Proposal).where(
                m.Proposal.shipment_id == ship.id, m.Proposal.id != prop.id,
                m.Proposal.status.in_(OPEN_STATES)).with_for_update()).scalars():
            release_holds(session, sib.id, "released")
            sib.status = "cancelled"
            sib.version += 1
        prop.status = "confirmed"
        prop.version += 1
        from ..docks.service import assign
        assign(session, prop, ship, veh, slot, now)  # xếp dock trong CÙNG transaction (khoá dock chống trùng lịch)
        session.add(m.OutboxJob(topic="proposal.confirmed", payload={"proposal_id": str(prop.id)},
                                dedupe_key=f"proposal.confirmed:{prop.id}"))
    session.flush()
    return prop, False


def reject(session: Session, actor: Actor, proposal_id: uuid.UUID, version: int, key: str, now: datetime) -> tuple[m.Proposal, bool]:
    if (dec := find_replay(session, actor, key, proposal_id, "reject")):
        return session.get(m.Proposal, dec.proposal_id), True
    expire_stale(session, now)
    prop = lock_proposal(session, proposal_id)
    ship, veh, slot = lock_resources(session, prop)
    orgs = party_orgs(ship, veh, slot)
    if not is_visible(actor, orgs):
        raise BookingError("NOT_FOUND", "Proposal not found", 404)
    mine = actor_parties(actor, orgs)
    if not mine and not can_hold(actor, orgs):
        raise BookingError("FORBIDDEN", "Your organization/role cannot reject this proposal", 403)
    if (dec := find_replay(session, actor, key, proposal_id, "reject")):
        return prop, True
    if prop.version != version:
        raise BookingError("VERSION_CONFLICT", f"Proposal version is {prop.version}, got {version}", 409)
    if prop.status == "expired":
        raise BookingError("PROPOSAL_EXPIRED", "Proposal or hold has expired", 409)
    if prop.status not in OPEN_STATES:
        raise BookingError("INVALID_STATE", f"Cannot reject a '{prop.status}' proposal", 409)
    release_holds(session, prop.id, "released")
    prop.status = "rejected"
    prop.version += 1
    _record(session, actor, prop, "reject", sorted(mine)[0] if mine else None, key)
    session.flush()
    return prop, False
