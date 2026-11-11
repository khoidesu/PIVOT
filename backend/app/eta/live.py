"""ETA trực tiếp (rule-based) cho chuyến đang chạy: quãng còn lại ÷ tốc độ QUAN SÁT được (từ vệt GPS), có khoảng P50/P90."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..tracking import geo, service as tracking


def observed_speed_kmh(session: Session, proposal_id, fallback: float) -> tuple[float, bool]:
    """(tốc độ km/h, có dữ liệu quan sát). Tính từ các điểm vệt gần nhất theo thời gian thực (không tin speed_kmh tự khai)."""
    pts = session.execute(select(m.TripTrack).where(m.TripTrack.proposal_id == proposal_id)
                          .order_by(m.TripTrack.at.desc()).limit(6)).scalars().all()
    if len(pts) < 2:
        return fallback, False
    km = sum(geo.haversine_km((a.lat, a.lng), (b.lat, b.lng)) for a, b in zip(pts[1:], pts[:-1]))
    hours = (pts[0].at - pts[-1].at).total_seconds() / 3600
    return (km / hours if hours > 0 else 0.0), True


def live(session: Session, prop: m.Proposal, ship: m.Shipment, veh: m.Vehicle, now: datetime, params: dict) -> dict | None:
    """ETA tới cổng ICD của chuyến đang chạy; None nếu chưa có vị trí. Xe đứng yên → stalled (không bịa ETA)."""
    if prop.status != "executing" or veh.lat is None:
        return None
    cfg = params["eta"]
    pts, _pickup_idx, cum = tracking.route_for(session, prop)
    along = geo.project(pts, cum, (veh.lat, veh.lng))
    remaining = max(cum[-1] - along, 0.0)
    speed, observed = observed_speed_kmh(session, prop.id, cfg["live_speed_kmh_fallback"])
    base = {"method": "rule-based/live", "confidence": "medium" if observed else "low (rule-based)", "remaining_km": round(remaining, 1),
            "speed_kmh": round(speed, 1), "model_version": cfg["model_version"]}
    if remaining < 0.05:
        return {**base, "p50": now.isoformat(), "p90": now.isoformat(), "stalled": False, "cutoff_risk": False}
    if speed < 1.0:
        return {**base, "p50": None, "p90": None, "stalled": True, "cutoff_risk": True}
    p50 = now + timedelta(hours=remaining / speed)
    p90 = now + timedelta(hours=remaining / (speed * cfg["live_p90_speed_factor"]), minutes=cfg["p90_buffer_minutes"])
    risk = ship.cutoff_at is not None and p90 + timedelta(minutes=params["handling_minutes"]) > ship.cutoff_at
    return {**base, "p50": p50.isoformat(), "p90": p90.isoformat(), "stalled": False, "cutoff_risk": risk}
