"""ETA luật (rule-based) có khoảng bất định P50/P90 — tham số trong bộ giả định có version (assume-v2).

P50 giữ nguyên ngữ nghĩa cũ (deadhead + transit) để hard gate không đổi quyết định; khung giờ cao điểm chỉ nới P90.
Nhãn trung thực: đây là LUẬT, độ tin cậy thấp — không phải mô hình ML đã huấn luyện.
"""
from datetime import datetime, timedelta, timezone


def band_for(dt: datetime, params: dict) -> str:
    cfg = params["eta"]
    hour = (dt.astimezone(timezone.utc) + timedelta(hours=cfg["tz_offset_hours"])).hour
    if hour in cfg["peak_am_hours"]:
        return "peak_am"
    if hour in cfg["peak_pm_hours"]:
        return "peak_pm"
    if hour in cfg["night_hours"]:
        return "night"
    return "normal"


def p90_extra_minutes(base_minutes: float, band: str, params: dict) -> int:
    cfg = params["eta"]
    return int(round(base_minutes * cfg["spread"][band] + cfg["p90_buffer_minutes"]))


def interval(p50: datetime, base_minutes: float, at: datetime, params: dict) -> dict:
    """P50/P90 của một mốc đến, theo khung giờ của thời điểm dự báo."""
    band = band_for(at, params)
    return {"p50": p50.isoformat(), "p90": (p50 + timedelta(minutes=p90_extra_minutes(base_minutes, band, params))).isoformat(), "band": band}


def build(pickup_p50: datetime, now: datetime, params: dict, cutoff_at: datetime | None = None) -> dict:
    """Đối tượng ETA lưu vào input_snapshot (giữ khoá `pickup` cũ để tương thích)."""
    dead, transit, handling = params["deadhead_minutes"], params["transit_minutes"], params["handling_minutes"]
    pickup = interval(pickup_p50, dead, now, params)
    icd_p50 = pickup_p50 + timedelta(minutes=transit)
    icd = interval(icd_p50, dead + transit, now, params)
    eta = {"pickup": pickup["p50"], "pickup_p90": pickup["p90"], "icd": icd["p50"], "icd_p90": icd["p90"], "band": pickup["band"],
           "method": params.get("eta_method", "rule-based"), "confidence": "low (rule-based)", "model_version": params["eta"]["model_version"]}
    if cutoff_at is not None:  # cờ MỀM (không phải hard gate): P90 tới ICD + bốc dỡ vượt cut-off
        eta["cutoff_risk_p90"] = datetime.fromisoformat(icd["p90"]) + timedelta(minutes=handling) > cutoff_at
    return eta
