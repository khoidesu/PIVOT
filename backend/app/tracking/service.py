"""Tracking & Tracing (brief Control Tower, chức năng 1). Vị trí đến qua sự kiện idempotent; mốc suy ra từ vị trí.

Toàn bộ toạ độ/đường đi ở prototype là MÔ PHỎNG (đường nội suy giữa các địa điểm trong DB, không phải đường bộ thật).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from ..eta import signals
from . import geo

R_PICKUP_KM = 0.6
R_GATE_KM = 0.6
MAX_TRACK_POINTS = 600
MILESTONE_LABELS = ["ASSIGNED", "AT_PICKUP", "DEPARTED_PICKUP", "AT_ICD_GATE", "COMPLETED"]


def _loc(session: Session, loc_id) -> geo.Point:
    loc = session.get(m.Location, loc_id)
    return (loc.lat, loc.lng)


def _endpoints(session: Session, prop: m.Proposal) -> tuple[geo.Point, geo.Point, geo.Point]:
    """(xuất phát = vị trí khả dụng của xe, điểm lấy hàng, đích = địa điểm giao của lô)."""
    ship, veh = session.get(m.Shipment, prop.shipment_id), session.get(m.Vehicle, prop.vehicle_id)
    win = session.execute(select(m.AvailabilityWindow).where(m.AvailabilityWindow.vehicle_id == veh.id)
                          .order_by(m.AvailabilityWindow.free_from.desc())).scalars().first()
    pickup, dest = _loc(session, ship.origin_location_id), _loc(session, ship.dest_location_id)
    return (_loc(session, win.location_id) if win else pickup), pickup, dest


def route_for(session: Session, prop: m.Proposal):
    """(điểm, chỉ số điểm lấy hàng, tích luỹ km). Ưu tiên tuyến đường bộ thật đã lưu (OSRM); chưa có → nội suy mô phỏng.
    Không bao giờ gọi mạng ở đây (hàm này nằm trên đường nóng của worker/giả lập)."""
    tr = session.get(m.TripRoute, prop.id)
    if tr is not None:
        pts = [(a, b) for a, b in tr.points]
        return pts, tr.pickup_index, geo.cumulative(pts)
    pts, pickup_idx = geo.build_route(*_endpoints(session, prop))
    return pts, pickup_idx, geo.cumulative(pts)


def ensure_road_route(session: Session, prop: m.Proposal) -> m.TripRoute | None:
    """Lưu tuyến đường bộ thật cho chuyến CHƯA chạy (hình học bất biến suốt chuyến). Idempotent; lỗi mạng/tắt → None (giữ tuyến mô phỏng)."""
    tr = session.get(m.TripRoute, prop.id)
    if tr is not None or prop.status != "confirmed":
        return tr
    road = signals.fetch_road_route(*_endpoints(session, prop))
    if road is None:
        return None
    try:
        with session.begin_nested():
            tr = m.TripRoute(proposal_id=prop.id, points=[list(p) for p in road["points"]], pickup_index=road["pickup_index"],
                             distance_km=road["distance_km"], duration_min=road["duration_min"], source=road["source"])
            session.add(tr)
            session.flush()
    except IntegrityError:  # hai yêu cầu cùng lưu: giữ bản đến trước
        tr = session.get(m.TripRoute, prop.id)
    return tr


def reached_milestones(session: Session, prop_id) -> set[str]:
    rows = session.execute(select(m.Event.payload).where(
        m.Event.entity_type == "proposal", m.Event.entity_id == prop_id, m.Event.event_type == "MILESTONE_REACHED")).scalars()
    return {p.get("milestone") for p in rows}


def _emit_milestone(session: Session, prop: m.Proposal, veh: m.Vehicle, name: str, at: datetime, along: float, total: float):
    """Sự kiện hệ thống idempotent: unique (source_system, source_event_id) → mỗi mốc đúng một lần dù gửi lặp/worker restart."""
    ev = m.Event(tenant_id=veh.tenant_id, entity_type="proposal", entity_id=prop.id, event_type="MILESTONE_REACHED",
                 occurred_at=at, received_at=datetime.now(timezone.utc), source_system="system",
                 source_event_id=f"ms:{prop.id}:{name}", quality_status="applied",
                 payload={"milestone": name, "along_km": round(along, 2), "progress_pct": round(100 * along / total) if total else 0})
    try:
        with session.begin_nested():
            session.add(ev)
            session.flush()
    except IntegrityError:
        pass


def record_position(session: Session, veh: m.Vehicle, ev: m.Event) -> None:
    """Gọi từ worker khi VEHICLE_POSITION có toạ độ: ghi vệt + suy ra mốc cho chuyến đang chạy của xe."""
    prop = session.execute(select(m.Proposal).where(m.Proposal.vehicle_id == veh.id, m.Proposal.status == "executing")
                           .order_by(m.Proposal.created_at.desc())).scalars().first()
    if prop is None:
        return
    p = ev.payload
    session.add(m.TripTrack(proposal_id=prop.id, vehicle_id=veh.id, at=ev.occurred_at, lat=p["lat"], lng=p["lng"],
                            speed_kmh=p.get("speed_kmh"), source="sim-gps" if ev.source_system == "sim-gps" else "gps"))
    n = session.execute(select(func.count()).select_from(m.TripTrack).where(m.TripTrack.proposal_id == prop.id)).scalar_one()
    if n > MAX_TRACK_POINTS:  # giới hạn dung lượng: bỏ điểm cũ nhất
        oldest = session.execute(select(m.TripTrack.id).where(m.TripTrack.proposal_id == prop.id)
                                 .order_by(m.TripTrack.at).limit(n - MAX_TRACK_POINTS)).scalars().all()
        session.execute(delete(m.TripTrack).where(m.TripTrack.id.in_(oldest)))
    pts, pickup_idx, cum = route_for(session, prop)
    along = geo.project(pts, cum, (p["lat"], p["lng"]))
    for name in geo.derive_milestones(along, cum[pickup_idx], cum[-1], R_PICKUP_KM, R_GATE_KM, reached_milestones(session, prop.id)):
        _emit_milestone(session, prop, veh, name, ev.occurred_at, along, cum[-1])


# ------------------------------------------------------------------ đọc (API)
def _visible_proposals(session: Session, actor, only_active: bool):
    stmt = (select(m.Proposal, m.Shipment, m.Vehicle, m.Slot)
            .join(m.Shipment, m.Shipment.id == m.Proposal.shipment_id)
            .join(m.Vehicle, m.Vehicle.id == m.Proposal.vehicle_id)
            .outerjoin(m.Slot, m.Slot.id == m.Proposal.slot_id)
            .where(m.Proposal.status.in_(("executing",) if only_active else ("confirmed", "executing", "completed"))))
    if actor.role != "dispatcher":  # lọc quyền NGAY trong SQL: nếu LIMIT trước rồi mới lọc thì chuyến cũ của người dùng bị chuyến mới của người khác đẩy khỏi danh sách
        stmt = stmt.where(or_(m.Shipment.tenant_id == actor.org_id, m.Vehicle.tenant_id == actor.org_id, m.Slot.node_org_id == actor.org_id))
    return session.execute(stmt.order_by(m.Proposal.created_at.desc()).limit(100)).all()


def trip_view(session: Session, prop: m.Proposal, ship: m.Shipment, veh: m.Vehicle, now: datetime) -> dict:
    from ..assumptions import get_active
    from ..eta import live as eta_live, ml
    pts, pickup_idx, cum = route_for(session, prop)
    total = cum[-1]
    reached = reached_milestones(session, prop.id)
    if prop.status == "completed":
        reached |= {"COMPLETED", "AT_PICKUP", "DEPARTED_PICKUP", "AT_ICD_GATE"}
    reached.add("ASSIGNED")
    pos = (veh.lat, veh.lng) if veh.lat is not None else None
    along = geo.project(pts, cum, pos) if pos and prop.status == "executing" else (total if prop.status == "completed" else 0.0)
    age = int((now - veh.position_updated_at).total_seconds()) if veh.position_updated_at else None
    return {
        "proposal_id": str(prop.id), "status": prop.status, "shipment_code": ship.code, "plate": veh.plate,
        "position": {"lat": veh.lat, "lng": veh.lng, "speed_kmh": veh.speed_kmh, "age_seconds": age} if pos else None,
        "progress_pct": round(100 * along / total) if total else 0, "remaining_km": round(max(total - along, 0), 1),
        "total_km": round(total, 1), "milestones": [{"code": c, "reached": c in reached} for c in MILESTONE_LABELS],
        "is_simulated": True,
        "eta": eta_live.live(session, prop, ship, veh, now, get_active(session).params) or ((prop.input_snapshot or {}).get("eta")),
        "cutoff_at": ship.cutoff_at,
        "eta_ml": ml.predict(now) if prop.status in ("confirmed", "executing") else None,  # chỉ khi mô hình được promote (dữ liệu mô phỏng)
        "route": [{"lat": a, "lng": b} for a, b in pts], "pickup_index": pickup_idx,
        "route_source": "osrm" if session.get(m.TripRoute, prop.id) else "simulated",  # đường bộ thật (OSRM) hay nội suy mô phỏng
        "geofences": [{"code": "AT_PICKUP", "lat": pts[pickup_idx][0], "lng": pts[pickup_idx][1], "radius_m": int(R_PICKUP_KM * 1000)},
                      {"code": "AT_ICD_GATE", "lat": pts[-1][0], "lng": pts[-1][1], "radius_m": int(R_GATE_KM * 1000)}],
    }


def list_trips(session: Session, actor, now: datetime) -> list[dict]:
    return [trip_view(session, p, sh, v, now) for p, sh, v, _ in _visible_proposals(session, actor, only_active=False)
            if p.status in ("confirmed", "executing")]


def trip_detail(session: Session, actor, proposal_id: uuid.UUID, now: datetime) -> dict | None:
    for p, sh, v, _ in _visible_proposals(session, actor, only_active=False):
        if p.id == proposal_id:
            out = trip_view(session, p, sh, v, now)
            tr = session.execute(select(m.TripTrack).where(m.TripTrack.proposal_id == p.id).order_by(m.TripTrack.at)).scalars().all()
            out["track"] = [{"at": t.at.isoformat(), "lat": t.lat, "lng": t.lng, "speed_kmh": t.speed_kmh} for t in tr]
            out["eta_signals"] = signals_view(session, p, out, now)
            return out
    return None


def signals_view(session: Session, prop: m.Proposal, view: dict, now: datetime) -> dict | None:
    """ETA luật + tín hiệu thật (đường bộ OSRM, thời tiết Open-Meteo) cho quãng còn lại. Chỉ ĐỌC (cache bộ nhớ), không ghi DB."""
    from ..assumptions import get_active
    if prop.status not in ("confirmed", "executing"):
        return None
    if not signals.enabled():
        return {"status": "disabled", "method": "rule-based", "version": signals.VERSION}
    road = session.get(m.TripRoute, prop.id)
    if road is None:
        return {"status": "fallback", "reason": "road_route_unavailable", "method": "rule-based", "version": signals.VERSION,
                "confidence": "low (rule-based)", "p50": None, "p90": None, "sources": {"route": None, "weather": None}}
    pos = view["position"] if view["status"] == "executing" and view["position"] else None
    mid = road.points[len(road.points) // 2]
    wx = signals.fetch_weather(pos["lat"] if pos else mid[0], pos["lng"] if pos else mid[1])
    frac = (view["remaining_km"] / view["total_km"]) if view["total_km"] else 1.0
    pts = road.points  # kẹt xe thật theo cả tuyến kế hoạch (xe → điểm lấy → ICD), cache theo tuyến chứ không theo vị trí xe → tiết kiệm hạn mức API
    wps = [tuple(pts[0]), tuple(pts[road.pickup_index]), tuple(pts[-1])] if road.pickup_index > 0 else [tuple(pts[0]), tuple(pts[-1])]
    out = signals.estimate({"source": road.source, "distance_km": road.distance_km, "duration_min": road.duration_min}, wx, frac, now,
                           get_active(session).params, signals.fetch_traffic(wps))
    out["health"] = signals.health()
    return out
