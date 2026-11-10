"""MatchScore (DRAFT 5.2) — chỉ chấm ứng viên ĐÃ qua hard gate.

- Mọi tiêu chí đưa về thang 0–1; trọng số lấy từ assumption_set và phải cộng bằng 1.
- Điểm ưu tiên (score) TÁCH khỏi số tiền tiết kiệm (estimated_saving_vnd): tiền chỉ là ước tính, không đưa vào điểm.
- Ứng viên đã qua gate nên đủ dữ liệu cho các tiêu chí; nếu vẫn thiếu thì tiêu chí = 0 và bị đánh dấu `missing`
  (không điền giá trị suy đoán).
- Tie-break xác định: score ↓, time_margin ↓, biển số ↑.
- Quãng đường là đường chim bay × hệ số đường bộ (cấu hình) — chỉ là xấp xỉ rule-based, UI phải ghi nhãn.
"""
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

DEFAULT_ROAD_FACTOR = 1.3
DEFAULT_MARGIN_CAP_MIN = 180


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass(frozen=True)
class Scored:
    score: float
    components: dict
    estimated_saving_vnd: int
    deadhead_km: float
    time_margin_minutes: float


def check_weights(weights: dict) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-9 or any(w < 0 for w in weights.values()):
        raise ValueError(f"score_weights must be >= 0 and sum to 1 (got {total})")


def score_candidate(shipment, vehicle, window_location, origin_location, eta_pickup, params: dict) -> Scored:
    weights = params["score_weights"]
    check_weights(weights)
    missing: list[str] = []

    # fit: mức lấp đầy xe (lô càng vừa xe càng tốt)
    if shipment.weight_kg is None or shipment.volume_m3 is None:
        fit = 0.0
        missing.append("fit")
    else:
        fit = _clamp01(max(shipment.weight_kg / vehicle.capacity_kg, shipment.volume_m3 / vehicle.capacity_m3))

    # time_margin: dư thời gian so với hạn lấy hàng
    if shipment.pickup_deadline is None or eta_pickup is None:
        margin_min, time_margin = 0.0, 0.0
        missing.append("time_margin")
    else:
        margin_min = (shipment.pickup_deadline - eta_pickup).total_seconds() / 60
        time_margin = _clamp01(margin_min / params.get("margin_cap_minutes", DEFAULT_MARGIN_CAP_MIN))

    # empty_km_saved: so km chạy rỗng tới điểm lấy với baseline
    baseline = params["empty_km_baseline"]
    deadhead_km = haversine_km(window_location.lat, window_location.lng, origin_location.lat, origin_location.lng) \
        * params.get("road_factor", DEFAULT_ROAD_FACTOR)
    saved_km = max(baseline - deadhead_km, 0.0)
    empty_km_saved = _clamp01(saved_km / baseline) if baseline > 0 else 0.0

    components = {
        "fit": round(fit, 4),
        "time_margin": round(time_margin, 4),
        "empty_km_saved": round(empty_km_saved, 4),
        "weights": weights,
        "missing": missing,
    }
    score = sum(weights[k] * components[k] for k in ("fit", "time_margin", "empty_km_saved"))
    return Scored(
        score=round(score, 6),
        components=components,
        estimated_saving_vnd=int(round(saved_km * params["cost_per_km_vnd"])),
        deadhead_km=round(deadhead_km, 1),
        time_margin_minutes=round(margin_min, 1),
    )


def rank_key(item) -> tuple:
    """Khoá sắp xếp tie-break xác định: score ↓, time_margin ↓, biển số ↑."""
    return (-round(item["scored"].score, 6), -item["scored"].time_margin_minutes, item["vehicle"].plate)
