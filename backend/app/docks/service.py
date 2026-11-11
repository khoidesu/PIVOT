"""Truck Appointment (brief Control Tower, chức năng 3): lịch hẹn xe tại dock, check-in / bốc dỡ / dwell time, NO_SHOW,
đề xuất dời lịch khi ETA đổi (ICD chấp nhận mới áp dụng).

Chống trùng lịch: khoá dòng các dock của ICD (FOR UPDATE, thứ tự id cố định → không deadlock) rồi kiểm tra chồng lấn trong CÙNG transaction.
Dữ liệu dock/lịch là MÔ PHỎNG.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..assumptions import get_active
from ..auth import Actor
from ..booking import service as bk

ACTIVE = ("scheduled", "checked_in", "unloading")
STEP = timedelta(minutes=5)
GRACE = timedelta(minutes=15)       # quá khung + ân hạn mà chưa check-in → NO_SHOW
QUEUE_LIMIT = timedelta(minutes=30)  # check-in nhưng chờ bốc dỡ quá lâu → DOCK_CONGESTION
OVERFLOW = timedelta(minutes=90)     # cho phép bắt đầu muộn hơn cuối slot tối đa 90′
SUGGEST_HORIZON = timedelta(hours=6)


def _ceil5(dt: datetime) -> datetime:
    """Làm tròn LÊN bội số 5 phút (không bao giờ sớm hơn dt)."""
    floored = dt.replace(second=0, microsecond=0)
    if floored == dt and dt.minute % 5 == 0:
        return dt
    return floored + timedelta(minutes=5 - dt.minute % 5)


def lock_docks(session: Session, node_org_id: uuid.UUID, location_id: uuid.UUID | None = None) -> list[m.Dock]:
    stmt = select(m.Dock).where(m.Dock.node_org_id == node_org_id, m.Dock.status == "active")
    if location_id:
        stmt = stmt.where(m.Dock.location_id == location_id)
    return list(session.execute(stmt.order_by(m.Dock.id).with_for_update()).scalars())


def _busy(session: Session, dock_id: uuid.UUID, exclude: uuid.UUID | None) -> list[tuple[datetime, datetime]]:
    stmt = select(m.DockAppointment.window_start, m.DockAppointment.window_end).where(
        m.DockAppointment.dock_id == dock_id, m.DockAppointment.status.in_(ACTIVE))
    if exclude:
        stmt = stmt.where(m.DockAppointment.id != exclude)
    return [(a, b) for a, b in session.execute(stmt)]


def free(busy: list[tuple[datetime, datetime]], start: datetime, end: datetime) -> bool:
    return all(end <= a or start >= b for a, b in busy)


def find_window(session: Session, docks: list[m.Dock], earliest: datetime, latest_start: datetime, minutes: int,
                exclude: uuid.UUID | None = None) -> tuple[m.Dock, datetime] | None:
    """Khung trống sớm nhất (mọi dock, bước 5′); hoà → dock có mã nhỏ hơn. Gọi khi ĐÃ khoá dock."""
    best: tuple[datetime, str, m.Dock] | None = None
    need = timedelta(minutes=minutes)
    for dock in sorted(docks, key=lambda d: d.code):
        busy = _busy(session, dock.id, exclude)
        t = _ceil5(earliest)
        while t <= latest_start:
            if free(busy, t, t + need):
                if best is None or t < best[0]:
                    best = (t, dock.code, dock)
                break
            t += STEP
    return (best[2], best[0]) if best else None


def arrival_at_icd(session: Session, prop: m.Proposal) -> datetime | None:
    """ETA tới ICD (luật) = ETA lấy hàng của chuyến + thời gian trung chuyển (assume-v2)."""
    pickup = ((prop.input_snapshot or {}).get("eta") or {}).get("pickup")
    return datetime.fromisoformat(pickup) + timedelta(minutes=get_active(session).params["transit_minutes"]) if pickup else None


def assign(session: Session, prop: m.Proposal, ship: m.Shipment, veh: m.Vehicle, slot: m.Slot | None, now: datetime):
    """Tự xếp dock khi chuyến được xác nhận. Không còn chỗ → ngoại lệ DOCK_CONGESTION cho ICD quyết (không ép ghép)."""
    if slot is None or session.execute(select(m.DockAppointment.id).where(m.DockAppointment.proposal_id == prop.id)).first():
        return None
    docks = lock_docks(session, slot.node_org_id, slot.location_id)
    arrive = arrival_at_icd(session, prop) or slot.start_at
    earliest = max(slot.start_at, arrive)
    latest_start = slot.end_at + OVERFLOW
    if ship.cutoff_at is not None:
        latest_start = min(latest_start, ship.cutoff_at)  # khung dock không được bắt đầu sau giờ chốt của lô
    found = find_window(session, docks, earliest, latest_start, max((d.handling_minutes for d in docks), default=30)) if docks else None
    if found is None:
        from ..incidents.service import raise_exception
        raise_exception(session, prop, "DOCK_CONGESTION", {"delay_minutes": 0, "reason": "NO_DOCK_WINDOW"}, now, source="event",
                        dedupe_key=f"dock-full:{prop.id}")
        return None
    dock, start = found
    appt = m.DockAppointment(dock_id=dock.id, proposal_id=prop.id, vehicle_id=veh.id, window_start=start,
                             window_end=start + timedelta(minutes=dock.handling_minutes), base_eta_at=arrive, eta_at=arrive, created_at=now)
    session.add(appt)
    session.flush()
    return appt


def cancel_for(session: Session, proposal_id: uuid.UUID) -> None:
    for a in session.execute(select(m.DockAppointment).where(m.DockAppointment.proposal_id == proposal_id,
                                                              m.DockAppointment.status.in_(ACTIVE)).with_for_update()).scalars():
        a.status, a.version = "cancelled", a.version + 1
        a.suggested_dock_id = a.suggested_start = a.suggested_end = a.suggestion_reason = None


# ---------------------------------------------------------------- sự kiện (worker)
def on_eta_delay(session: Session, prop: m.Proposal, delay_minutes: int) -> None:
    """ETA đổi → cập nhật ETA của lịch hẹn; nếu xe sẽ đến sau khung đã đặt thì ĐỀ XUẤT khung mới (ICD chấp nhận mới áp dụng)."""
    appt = session.execute(select(m.DockAppointment).where(m.DockAppointment.proposal_id == prop.id,
                                                           m.DockAppointment.status == "scheduled").with_for_update()).scalar_one_or_none()
    if appt is None or appt.base_eta_at is None:
        return
    dock = session.get(m.Dock, appt.dock_id)
    appt.eta_at = appt.base_eta_at + timedelta(minutes=delay_minutes)
    if appt.eta_at <= appt.window_start:
        appt.suggested_dock_id = appt.suggested_start = appt.suggested_end = appt.suggestion_reason = None
        return
    docks = lock_docks(session, dock.node_org_id, dock.location_id)
    ship = session.get(m.Shipment, prop.shipment_id)
    horizon = appt.eta_at + SUGGEST_HORIZON
    if ship is not None and ship.cutoff_at is not None:
        horizon = min(horizon, ship.cutoff_at)  # không đề xuất khung sau cut-off (người quyết định xử lý ngoại lệ ETA)
    found = find_window(session, docks, appt.eta_at, horizon, dock.handling_minutes, exclude=appt.id)
    if found:
        d, start = found
        appt.suggested_dock_id, appt.suggested_start = d.id, start
        appt.suggested_end, appt.suggestion_reason = start + timedelta(minutes=d.handling_minutes), "ETA_DELAY"
    appt.version += 1


def apply_dock_event(session: Session, prop: m.Proposal, ev: m.Event) -> str:
    appt = session.execute(select(m.DockAppointment).where(m.DockAppointment.proposal_id == prop.id).with_for_update()).scalar_one_or_none()
    if appt is None:
        return "invalid"
    t, at = ev.event_type, ev.occurred_at
    order = {"scheduled": 0, "checked_in": 1, "unloading": 2, "completed": 3}
    cur = order.get(appt.status)
    if cur is None:  # no_show/cancelled: không nhận thêm
        return "invalid"
    if t == "GATE_CHECK_IN":
        if cur >= 1:
            return "late"
        appt.status, appt.checked_in_at = "checked_in", at
        appt.suggested_dock_id = appt.suggested_start = appt.suggested_end = appt.suggestion_reason = None
    elif t == "UNLOAD_STARTED":
        if cur >= 2:
            return "late"
        if cur < 1:
            return "invalid"  # chưa check-in → không thể bắt đầu bốc dỡ
        appt.status, appt.unloading_started_at = "unloading", at
    elif t == "UNLOAD_COMPLETED":
        if cur >= 3:
            return "late"
        if cur < 2:
            return "invalid"
        appt.status, appt.completed_at = "completed", at
        appt.dwell_minutes = max(0, int((at - appt.checked_in_at).total_seconds() // 60))
    appt.version += 1
    return "applied"


def sweep(session: Session, now: datetime) -> dict:
    """NO_SHOW (quá khung + ân hạn chưa check-in) và DOCK_CONGESTION (chờ bốc dỡ quá lâu). Idempotent."""
    from ..incidents.service import raise_exception
    no_show = queue = 0
    for appt in session.execute(select(m.DockAppointment).where(m.DockAppointment.status.in_(("scheduled", "checked_in"))).with_for_update()).scalars():
        prop = session.get(m.Proposal, appt.proposal_id)
        if appt.status == "scheduled" and now > appt.window_end + GRACE:
            appt.status, appt.version = "no_show", appt.version + 1
            raise_exception(session, prop, "NO_SHOW", {"delay_minutes": int((now - appt.window_end).total_seconds() // 60)}, now,
                            source="sweep", dedupe_key=f"noshow:{appt.id}")
            no_show += 1
        elif appt.status == "checked_in" and appt.checked_in_at and now - appt.checked_in_at > QUEUE_LIMIT:
            if raise_exception(session, prop, "DOCK_CONGESTION", {"delay_minutes": int((now - appt.checked_in_at).total_seconds() // 60),
                                                                   "reason": "QUEUE"}, now, source="sweep", dedupe_key=f"queue:{appt.id}"):
                queue += 1
    return {"no_show": no_show, "queue": queue}


# ---------------------------------------------------------------- thao tác của người dùng
def _load(session: Session, appt_id: uuid.UUID) -> tuple[m.DockAppointment, m.Dock]:
    appt = session.execute(select(m.DockAppointment).where(m.DockAppointment.id == appt_id).with_for_update()).scalar_one_or_none()
    if appt is None:
        raise bk.BookingError("NOT_FOUND", "Appointment not found", 404)
    return appt, session.get(m.Dock, appt.dock_id)


def _may_manage(actor: Actor, dock: m.Dock) -> bool:
    return actor.role == "dispatcher" or (actor.role == "node_operator" and actor.org_id == dock.node_org_id)


def reschedule(session: Session, actor: Actor, appt_id: uuid.UUID, version: int, start: datetime, dock_id: uuid.UUID | None) -> m.DockAppointment:
    appt0 = session.get(m.DockAppointment, appt_id)
    if appt0 is None:
        raise bk.BookingError("NOT_FOUND", "Appointment not found", 404)
    dock0 = session.get(m.Dock, appt0.dock_id)
    if not _may_manage(actor, dock0):
        raise bk.BookingError("NOT_FOUND" if actor.role != "node_operator" else "FORBIDDEN", "Only the terminal can reschedule", 404 if actor.role != "node_operator" else 403)
    lock_docks(session, dock0.node_org_id)  # khoá mọi dock của ICD trước khi đọc lịch
    appt, dock = _load(session, appt_id)
    if appt.version != version:
        raise bk.BookingError("VERSION_CONFLICT", f"Appointment version is {appt.version}", 409)
    if appt.status != "scheduled":
        raise bk.BookingError("INVALID_STATE", f"Cannot reschedule a '{appt.status}' appointment", 409)
    target = session.get(m.Dock, dock_id) if dock_id else dock
    if target is None or target.node_org_id != dock.node_org_id or target.status != "active":
        raise bk.BookingError("VALIDATION", "Unknown dock", 422)
    end = start + timedelta(minutes=target.handling_minutes)
    if not free(_busy(session, target.id, appt.id), start, end):
        raise bk.BookingError("DOCK_CONFLICT", "That window overlaps another appointment", 409)
    appt.dock_id, appt.window_start, appt.window_end, appt.version = target.id, start, end, appt.version + 1
    appt.suggested_dock_id = appt.suggested_start = appt.suggested_end = appt.suggestion_reason = None
    session.flush()
    return appt


def accept_suggestion(session: Session, actor: Actor, appt_id: uuid.UUID, version: int) -> m.DockAppointment:
    appt0 = session.get(m.DockAppointment, appt_id)
    if appt0 is None:
        raise bk.BookingError("NOT_FOUND", "Appointment not found", 404)
    dock0 = session.get(m.Dock, appt0.dock_id)
    if not (actor.role == "node_operator" and actor.org_id == dock0.node_org_id):
        raise bk.BookingError("NOT_FOUND" if actor.role != "node_operator" else "FORBIDDEN", "Only the terminal can accept a new window", 404 if actor.role != "node_operator" else 403)
    lock_docks(session, dock0.node_org_id)
    appt, _dock = _load(session, appt_id)
    if appt.version != version:
        raise bk.BookingError("VERSION_CONFLICT", f"Appointment version is {appt.version}", 409)
    if appt.status != "scheduled" or appt.suggested_start is None:
        raise bk.BookingError("NO_SUGGESTION", "There is no pending suggestion", 409)
    if not free(_busy(session, appt.suggested_dock_id, appt.id), appt.suggested_start, appt.suggested_end):
        raise bk.BookingError("DOCK_CONFLICT", "The suggested window is no longer free", 409)
    appt.dock_id, appt.window_start, appt.window_end = appt.suggested_dock_id, appt.suggested_start, appt.suggested_end
    appt.suggested_dock_id = appt.suggested_start = appt.suggested_end = appt.suggestion_reason = None
    appt.version += 1
    session.flush()
    return appt


# ---------------------------------------------------------------- đọc
def board(session: Session, actor: Actor, now: datetime) -> dict:
    rows = session.execute(select(m.DockAppointment, m.Dock, m.Proposal, m.Shipment, m.Vehicle)
                           .join(m.Dock, m.Dock.id == m.DockAppointment.dock_id)
                           .join(m.Proposal, m.Proposal.id == m.DockAppointment.proposal_id)
                           .join(m.Shipment, m.Shipment.id == m.Proposal.shipment_id)
                           .join(m.Vehicle, m.Vehicle.id == m.DockAppointment.vehicle_id)
                           .where(m.DockAppointment.window_end > now - timedelta(hours=6))).all()
    mine = [r for r in rows if actor.role == "dispatcher" or actor.org_id in (r[1].node_org_id, r[3].tenant_id, r[4].tenant_id)]
    my_dock_orgs = {r[1].node_org_id for r in mine}
    if actor.role == "node_operator":
        my_dock_orgs.add(actor.org_id)
    dock_rows = list(session.execute(select(m.Dock).where(m.Dock.status == "active").order_by(m.Dock.node_org_id, m.Dock.code)).scalars()) \
        if actor.role == "dispatcher" else list(session.execute(select(m.Dock).where(m.Dock.node_org_id.in_(my_dock_orgs), m.Dock.status == "active")
                                                              .order_by(m.Dock.node_org_id, m.Dock.code)).scalars()) if my_dock_orgs else []
    orgs = {o.id: o.name for o in session.execute(select(m.Organization)).scalars()}
    docks = {d.id: d for d in dock_rows}
    visible_ids = {r[0].id for r in mine}

    def one(appt, dock, prop, ship, veh):
        sug_dock = docks.get(appt.suggested_dock_id)
        node = actor.role == "node_operator" and actor.org_id == dock.node_org_id
        carrier = actor.role == "carrier" and actor.org_id == veh.tenant_id
        return {"id": appt.id, "proposal_id": appt.proposal_id, "dock_id": appt.dock_id, "dock_code": dock.code, "status": appt.status,
                "window_start": appt.window_start, "window_end": appt.window_end, "eta_at": appt.eta_at,
                "checked_in_at": appt.checked_in_at, "unloading_started_at": appt.unloading_started_at, "completed_at": appt.completed_at,
                "dwell_minutes": appt.dwell_minutes, "version": appt.version, "shipment_code": ship.code, "plate": veh.plate,
                "late_minutes": max(0, int((appt.eta_at - appt.window_start).total_seconds() // 60)) if appt.eta_at and appt.status == "scheduled" else 0,
                "suggestion": {"dock_code": sug_dock.code if sug_dock else None, "window_start": appt.suggested_start, "window_end": appt.suggested_end,
                               "reason": appt.suggestion_reason} if appt.suggested_start else None,
                "can_reschedule": appt.status == "scheduled" and (node or actor.role == "dispatcher"),
                "can_accept_suggestion": appt.status == "scheduled" and node and appt.suggested_start is not None,
                "can_check_in": appt.status == "scheduled" and carrier and prop.status == "executing",
                "can_start": appt.status == "checked_in" and node, "can_complete": appt.status == "unloading" and node, "is_simulated": True}

    appts = [one(*r) for r in mine]
    busy = [{"dock_id": r[0].dock_id, "window_start": r[0].window_start, "window_end": r[0].window_end, "status": "busy"}
            for r in rows if r[0].id not in visible_ids and r[0].status in ACTIVE and r[0].dock_id in docks]
    horizon = now + timedelta(hours=8)
    booked = sum(max(0, (min(a["window_end"], horizon) - max(a["window_start"], now)).total_seconds()) / 60 for a in appts if a["status"] in ACTIVE)
    dwell = [a["dwell_minutes"] for a in appts if a["dwell_minutes"] is not None]
    return {"docks": [{"id": d.id, "code": d.code, "node_org_name": orgs.get(d.node_org_id), "handling_minutes": d.handling_minutes} for d in dock_rows],
            "appointments": appts, "busy": busy, "is_simulated": True,
            "kpis": {"dock_count": len(dock_rows), "utilization_pct": round(100 * booked / (len(dock_rows) * 8 * 60)) if dock_rows else 0,
                     "queue": sum(1 for a in appts if a["status"] == "checked_in"), "no_show": sum(1 for a in appts if a["status"] == "no_show"),
                     "avg_dwell_minutes": round(sum(dwell) / len(dwell)) if dwell else None, "scheduled": sum(1 for a in appts if a["status"] == "scheduled")}}
