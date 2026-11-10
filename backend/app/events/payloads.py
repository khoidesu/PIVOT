"""Validate payload theo từng loại sự kiện NGAY khi nhận (422), không để worker đoán/đổ lỗi (poison message)."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import models as m
from ..booking.service import BookingError

MAX_EMPTY_KM = 500.0          # số đo km chạy rỗng hợp lệ: 0..500
MAX_DELAY_MIN = 24 * 60
MAX_FUTURE_SKEW = timedelta(minutes=5)  # sự kiện "từ tương lai" quá 5 phút là dữ liệu lỗi


def _bad(msg: str):
    raise BookingError("VALIDATION", msg, 422)


def _num(v, name, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:  # chặn bool, chuỗi, NaN
        _bad(f"payload.{name} must be a number")
    if not lo <= v <= hi:
        _bad(f"payload.{name} must be between {lo} and {hi}")
    return float(v)


def _aware(v, name) -> datetime:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        _bad(f"payload.{name} must be an ISO datetime")
    if d.tzinfo is None:
        _bad(f"payload.{name} must include a timezone")
    return d


def validate(session: Session, event_type: str, payload: dict, occurred_at: datetime, now: datetime) -> dict:
    if occurred_at > now + MAX_FUTURE_SKEW:
        _bad("occurred_at is in the future")
    p = dict(payload or {})
    if event_type == "TRIP_COMPLETED":
        if "actual_empty_km" in p:
            p["actual_empty_km"] = _num(p["actual_empty_km"], "actual_empty_km", 0, MAX_EMPTY_KM)
    elif event_type == "ETA_UPDATED":
        if "delay_minutes" not in p:
            _bad("payload.delay_minutes is required")
        p["delay_minutes"] = int(_num(p["delay_minutes"], "delay_minutes", 1, MAX_DELAY_MIN))
    elif event_type in ("VEHICLE_POSITION", "VEHICLE_AVAILABLE"):
        loc = p.get("location_id")
        if event_type == "VEHICLE_AVAILABLE" and loc is None:
            _bad("payload.location_id is required")
        if loc is not None:
            try:
                lid = uuid.UUID(str(loc))
            except ValueError:
                _bad("payload.location_id must be a UUID")
            if session.get(m.Location, lid) is None:
                _bad("payload.location_id does not exist")
            p["location_id"] = str(lid)
        if event_type == "VEHICLE_AVAILABLE":
            a, b = _aware(p.get("free_from"), "free_from"), _aware(p.get("free_to"), "free_to")
            if not a < b:
                _bad("payload.free_from must be before free_to")
            p["free_from"], p["free_to"] = a.isoformat(), b.isoformat()
    return p
