"""Bộ giả lập GPS (MÔ PHỎNG). `tick` đẩy từng chuyến đang chạy dọc tuyến và phát VEHICLE_POSITION qua đường nhận sự kiện thật
(danh nghĩa nhà vận tải sở hữu xe) → vẫn qua phân quyền, idempotency, outbox, worker như tin từ thiết bị thật."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import Actor
from ..events import service as events
from ..tracking import geo, service as tracking

MODES = {"normal": 45.0, "slow": 12.0, "breakdown": 0.0, "detour": 30.0}  # km/h thực tế của xe mô phỏng
DETOUR_OFFSET_DEG = 0.012


def _carrier_actor(session: Session, veh: m.Vehicle) -> Actor:
    org = session.get(m.Organization, veh.tenant_id)
    return Actor(user_id=uuid.UUID(int=0), user_name="gps-simulator", org_id=org.id, org_name=org.name,
                 org_type=org.org_type, role="carrier")


def start(session: Session, proposal_id: uuid.UUID, now: datetime, time_scale: float = 20.0) -> m.SimTrip:
    prop = session.get(m.Proposal, proposal_id)
    if prop is None or prop.status not in ("confirmed", "executing"):
        raise ValueError("Only a confirmed/executing trip can be simulated")
    veh = session.get(m.Vehicle, prop.vehicle_id)
    tracking.ensure_road_route(session, prop)  # đường bộ thật nếu có mạng (chỉ khi chưa chạy); lỗi → giữ tuyến nội suy
    sim = session.get(m.SimTrip, proposal_id)
    if sim is None:
        sim = m.SimTrip(proposal_id=proposal_id, running=True, mode="normal", along_km=0.0, time_scale=time_scale, updated_at=now)
        session.add(sim)
    else:
        sim.running, sim.updated_at, sim.time_scale = True, now, time_scale
    if prop.status == "confirmed":  # chuyến bắt đầu bằng sự kiện thật, không đổi trạng thái trực tiếp
        events.ingest(session, _carrier_actor(session, veh), {
            "entity_type": "proposal", "entity_id": prop.id, "event_type": "TRIP_STARTED", "occurred_at": now,
            "source_system": "sim-gps", "source_event_id": f"sim:start:{prop.id}", "payload": {}}, now)
    session.flush()
    return sim


def set_mode(session: Session, proposal_id: uuid.UUID, mode: str) -> m.SimTrip:
    if mode not in MODES:
        raise ValueError("Unknown mode")
    sim = session.get(m.SimTrip, proposal_id)
    if sim is None:
        raise ValueError("Simulation not started")
    sim.mode = mode
    return sim


INCIDENT_BY_MODE = {"slow": ("TRAFFIC_INCIDENT", 30), "breakdown": ("BREAKDOWN", 0)}


def report_mode_incident(session: Session, proposal_id: uuid.UUID, now: datetime) -> bool:
    """Thiết bị mô phỏng báo sự cố tương ứng với chế độ nhiễu (đi qua đường nhận sự kiện thật, idempotent)."""
    sim = session.get(m.SimTrip, proposal_id)
    prop = session.get(m.Proposal, proposal_id)
    if sim is None or sim.mode not in INCIDENT_BY_MODE or prop is None:
        return False
    kind, delay = INCIDENT_BY_MODE[sim.mode]
    veh = session.get(m.Vehicle, prop.vehicle_id)
    events.ingest(session, _carrier_actor(session, veh), {
        "entity_type": "proposal", "entity_id": prop.id, "event_type": "INCIDENT_REPORTED", "occurred_at": now,
        "source_system": "sim-gps", "source_event_id": f"sim:inc:{prop.id}:{sim.mode}:{sim.seq}",
        "payload": {"kind": kind, "delay_minutes": delay, "note": f"simulated {sim.mode}"}}, now)
    return True


def tick(session: Session, now: datetime) -> int:
    """Một bước mô phỏng cho mọi chuyến đang chạy; trả số vị trí đã phát. Xác định: chỉ phụ thuộc trạng thái + `now`."""
    sent = 0
    for sim in session.execute(select(m.SimTrip).where(m.SimTrip.running.is_(True)).with_for_update()).scalars().all():
        prop = session.get(m.Proposal, sim.proposal_id)
        if prop is None or prop.status != "executing":
            continue  # chưa bắt đầu (chờ worker áp TRIP_STARTED) hoặc đã kết thúc
        veh = session.get(m.Vehicle, prop.vehicle_id)
        pts, _, cum = tracking.route_for(session, prop)
        dt_h = max((now - sim.updated_at).total_seconds(), 0) / 3600 * sim.time_scale
        speed = MODES[sim.mode]
        sim.along_km = min(sim.along_km + speed * dt_h, cum[-1])
        sim.updated_at, sim.seq = now, sim.seq + 1
        lat, lng = geo.point_at(pts, cum, sim.along_km)
        if sim.mode == "detour":
            lat += DETOUR_OFFSET_DEG
        events.ingest(session, _carrier_actor(session, veh), {
            "entity_type": "vehicle", "entity_id": veh.id, "event_type": "VEHICLE_POSITION", "occurred_at": now,
            "source_system": "sim-gps", "source_event_id": f"sim:{prop.id}:{sim.seq}",
            "payload": {"lat": round(lat, 6), "lng": round(lng, 6), "speed_kmh": speed if sim.along_km < cum[-1] else 0.0}}, now)
        sent += 1
        if sim.along_km >= cum[-1]:
            sim.running = False  # tới cổng ICD: dừng giả lập (hoàn tất chuyến vẫn do nhà vận tải báo bằng sự kiện)
    return sent
