"""Đội xe của nhà vận tải: (1) làm tươi vị trí/khung rảnh khi đăng nhập / định kỳ; (2) bãi đậu + khoảng cách minh bạch.

Mọi dữ liệu ở đây là MÔ PHỎNG (không có GPS thật). Việc làm tươi KHÔNG đi tắt: nó phát `VEHICLE_POSITION` / `VEHICLE_AVAILABLE` qua đúng đường
nhận sự kiện (`events.ingest` → outbox → worker) nên vẫn có phân quyền, idempotency và audit; ngưỡng `DATA_STALE` (5 phút) không bị nới.
"""
import hashlib
import math
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .assumptions import get_active
from .auth import Actor
from .eta import baseline
from .events import service as events
from .matching import score

NS = uuid.UUID("6f1c6c1e-0000-4000-8000-00000000b002")

# MÔ HÌNH NHÀ XE (giả định mô phỏng, nói rõ trên giao diện): mỗi nhà xe (tổ chức vận tải) có MỘT vị trí nhà xe cố định, nằm trong bán kính
# 5 km quanh điểm lấy hàng; xe KHÔNG chở hàng luôn đậu ở đó (sau khi giao xong cũng quay về đó). Chỉ xe đang giữ/đang chạy mới rời nhà xe.
PICKUP_RADIUS_KM = 5.0
BASE_MIN_OFFSET_KM = 0.8   # nhà xe cách tâm các điểm lấy trong khoảng này…
BASE_MAX_OFFSET_KM = 2.2   # …nên cách MỌI điểm lấy < 5 km (các KCN mẫu cách nhau ~2,8 km → tối đa ~3,6 km)
FALLBACK_PICKUPS = ((10.90, 106.74), (10.92, 106.72))  # trùng KCN seed; chỉ dùng khi DB chưa có điểm lấy nào
DEFAULT_WINDOW_HOURS = 9  # khung rảnh gia hạn thêm khi làm tươi (cấu hình `fleet_window_hours` trong bộ giả định, nếu có)
REFRESH_BUCKET_SECONDS = 60  # gọi lặp trong cùng phút → cùng source_event_id → không nhân đôi tác động


def base_point(pickups, key: str, min_km: float = BASE_MIN_OFFSET_KM, max_km: float = BASE_MAX_OFFSET_KM) -> tuple[float, float]:
    """Toạ độ nhà xe xác định theo `key`: lệch tâm các điểm lấy hàng một khoảng [min_km, max_km] theo hướng ngẫu nhiên-xác định (băm `key`)."""
    pts = list(pickups) or list(FALLBACK_PICKUPS)
    lat0, lng0 = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    h = hashlib.sha256(key.encode()).digest()
    angle = int.from_bytes(h[:2], "big") / 65535 * 2 * math.pi
    r = min_km + int.from_bytes(h[2:4], "big") / 65535 * (max_km - min_km)
    return (lat0 + r * math.sin(angle) / 110.57, lng0 + r * math.cos(angle) / (111.32 * math.cos(math.radians(lat0))))


def base_for_org(session: Session, org: m.Organization) -> m.Location:
    """Nhà xe của một tổ chức vận tải (tạo nếu chưa có; id cố định theo tổ chức nên idempotent, DB cũ cũng được vá)."""
    loc_id = uuid.uuid5(NS, f"base:{org.id}")
    loc = session.get(m.Location, loc_id)
    if loc is None:
        zones = session.execute(select(m.Location).where(m.Location.kind == "industrial_zone")).scalars().all()
        lat, lng = base_point([(z.lat, z.lng) for z in zones], str(org.id))
        label = org.name.split(" · ")[0]
        loc = m.Location(id=loc_id, name=f"Nhà xe {label} (mô phỏng)"[:200], kind="carrier_base", lat=round(lat, 6), lng=round(lng, 6))
        session.add(loc)
        session.flush()
    return loc


def return_to_base(session: Session, veh: m.Vehicle) -> None:
    """Xe đã giao xong (không chở hàng nữa) → quay về nhà xe: địa điểm của khung rảnh mới nhất = nhà xe."""
    org = session.get(m.Organization, veh.tenant_id)
    win = session.execute(select(m.AvailabilityWindow).where(m.AvailabilityWindow.vehicle_id == veh.id)
                          .order_by(m.AvailabilityWindow.free_from.desc())).scalars().first()
    if org is not None and win is not None:
        win.location_id = base_for_org(session, org).id


# ------------------------------------------------------------------ 1. làm tươi đội xe
def _latest_windows(session: Session, vehicle_ids: list[uuid.UUID]) -> dict[uuid.UUID, m.AvailabilityWindow]:
    out: dict[uuid.UUID, m.AvailabilityWindow] = {}
    for w in session.execute(select(m.AvailabilityWindow).where(m.AvailabilityWindow.vehicle_id.in_(vehicle_ids))
                             .order_by(m.AvailabilityWindow.free_from)).scalars():
        out[w.vehicle_id] = w  # cửa sổ muộn nhất ghi đè (khớp cách bộ ghép chọn)
    return out


def _busy_vehicle_ids(session: Session, vehicle_ids: list[uuid.UUID]) -> tuple[set, set]:
    """(xe đang giữ/cam kết, xe đang chạy chuyến)."""
    reserved = set(session.execute(select(m.Reservation.resource_id).where(
        m.Reservation.resource_type == "vehicle", m.Reservation.resource_id.in_(vehicle_ids),
        m.Reservation.status.in_(("held", "committed")))).scalars())
    running = set(session.execute(select(m.Proposal.vehicle_id).where(
        m.Proposal.vehicle_id.in_(vehicle_ids), m.Proposal.status == "executing")).scalars())
    return reserved, running


def refresh_fleet(session: Session, actor: Actor, now: datetime) -> dict:
    """Làm tươi vị trí + khung rảnh của xe ĐANG RẢNH của tổ chức. Bỏ qua xe offline (không tự bật lại), xe đang giữ/cam kết/đang chạy
    (không ghi đè GPS của chuyến). Vị trí = NHÀ XE của tổ chức (xe không chở hàng luôn đậu ở đó), không phải toạ độ ngẫu nhiên."""
    horizon = timedelta(hours=get_active(session).params.get("fleet_window_hours", DEFAULT_WINDOW_HOURS))
    org = session.get(m.Organization, actor.org_id)
    base = base_for_org(session, org)  # xe rảnh luôn ở nhà xe
    vehs = session.execute(select(m.Vehicle).where(m.Vehicle.tenant_id == actor.org_id).order_by(m.Vehicle.plate)).scalars().all()
    ids = [v.id for v in vehs]
    wins = _latest_windows(session, ids) if ids else {}
    reserved, running = _busy_vehicle_ids(session, ids) if ids else (set(), set())
    bucket = int(now.timestamp() // REFRESH_BUCKET_SECONDS)
    skipped = {"offline": 0, "busy": 0, "no_window": 0}
    updated = extended = duplicates = 0
    for veh in vehs:
        if veh.status == "offline":
            skipped["offline"] += 1
            continue
        if veh.status != "available" or veh.id in reserved or veh.id in running:
            skipped["busy"] += 1
            continue
        win = wins.get(veh.id)
        if win is None:
            skipped["no_window"] += 1
            continue
        _, dup = events.ingest(session, actor, {
            "entity_type": "vehicle", "entity_id": veh.id, "event_type": "VEHICLE_POSITION", "occurred_at": now,
            "source_system": "sim-login", "source_event_id": f"auto:pos:{veh.id}:{bucket}",
            "payload": {"location_id": str(base.id)}}, now)  # VEHICLE_POSITION có location_id → khung rảnh cũng chuyển về nhà xe
        duplicates += int(dup)
        updated += int(not dup)
        # Khung rảnh sắp/đã hết → gia hạn (chỉ khi xe đã rảnh từ trước: không đổi giờ rảnh trong tương lai)
        if win.free_from <= now and win.free_to < now + horizon / 2:
            _, dup2 = events.ingest(session, actor, {
                "entity_type": "vehicle", "entity_id": veh.id, "event_type": "VEHICLE_AVAILABLE", "occurred_at": now,
                "source_system": "sim-login", "source_event_id": f"auto:avail:{veh.id}:{bucket}",
                "payload": {"location_id": str(base.id), "free_from": win.free_from.isoformat(),
                            "free_to": (now + horizon).isoformat()}}, now)
            extended += int(not dup2)
    return {"updated": updated, "window_extended": extended, "already_fresh": duplicates, "skipped": skipped,
            "at": now.isoformat(), "is_simulated": True}


# ------------------------------------------------------------------ 2. bãi đậu + khoảng cách minh bạch
def availability_state(veh: m.Vehicle, win: m.AvailabilityWindow | None, reserved: bool, running: bool, now: datetime) -> dict:
    """Trạng thái dễ hiểu của xe: empty | reserved | executing | offline | window_expired | free_later | no_window (+ lý do máy đọc được)."""
    if veh.status == "offline":
        return {"state": "offline", "reason": "VEHICLE_OFFLINE"}
    if running:
        return {"state": "executing", "reason": "TRIP_IN_PROGRESS"}
    if reserved or veh.status == "committed":
        return {"state": "reserved", "reason": "HELD_OR_COMMITTED"}
    if win is None:
        return {"state": "no_window", "reason": "NO_AVAILABILITY_WINDOW"}
    if win.free_to < now:
        return {"state": "window_expired", "reason": "WINDOW_ENDED"}
    if win.free_from > now:
        return {"state": "free_later", "reason": "FREE_LATER"}
    return {"state": "empty", "reason": "OK"}


def vehicle_views(session: Session, vehicles: list[m.Vehicle], now: datetime, to_location: m.Location | None = None) -> list[dict]:
    """Xe + bãi đang đậu + khung rảnh + trạng thái; có `to_location` thì thêm khoảng cách (ƯỚC TÍNH: đường chim bay × hệ số đường bộ) và ETA tới đó.
    Truy vấn theo lô (không N+1)."""
    if not vehicles:
        return []
    ids = [v.id for v in vehicles]
    params = get_active(session).params
    wins = _latest_windows(session, ids)
    reserved, running = _busy_vehicle_ids(session, ids)
    locs = {x.id: x for x in session.execute(select(m.Location).where(m.Location.id.in_({w.location_id for w in wins.values()}))).scalars()} if wins else {}
    road = params.get("road_factor", score.DEFAULT_ROAD_FACTOR)
    speed = params["eta"]["live_speed_kmh_fallback"]
    out = []
    for v in vehicles:
        win = wins.get(v.id)
        yard = locs.get(win.location_id) if win else None
        row = {"id": v.id, "tenant_id": v.tenant_id, "plate": v.plate, "cargo_types": v.cargo_types, "capacity_kg": v.capacity_kg,
               "capacity_m3": v.capacity_m3, "status": v.status, "position_updated_at": v.position_updated_at, "is_simulated": v.is_simulated,
               "yard": None if yard is None else {"id": yard.id, "name": yard.name, "kind": yard.kind, "lat": yard.lat, "lng": yard.lng},
               "free_from": win.free_from if win else None, "free_to": win.free_to if win else None,
               "availability": availability_state(v, win, v.id in reserved, v.id in running, now),
               "position_age_seconds": int((now - v.position_updated_at).total_seconds()) if v.position_updated_at else None,
               "distance_to_target_km": None, "distance_method": None, "deadhead_eta": None}
        if to_location is not None and yard is not None:
            km = round(score.haversine_km(yard.lat, yard.lng, to_location.lat, to_location.lng) * road, 1)
            minutes = km / speed * 60
            iv = baseline.interval(now + timedelta(minutes=minutes), minutes, now, params)
            row.update(distance_to_target_km=km, distance_method="estimate",
                       deadhead_eta={"minutes": round(minutes), "p50": iv["p50"], "p90": iv["p90"], "method": "rule-based (distance / speed)"})
        out.append(row)
    return out
