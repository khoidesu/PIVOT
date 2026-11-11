"""Tầng 2 của ETA: tín hiệu THẬT từ API công khai, cộng vào ETA luật dưới dạng hệ số điều chỉnh.

- Tuyến đường bộ thật + thời gian lái "thông thoáng": OSRM (OpenStreetMap, miễn phí, không khoá). Lưu ý trung thực: OSRM công khai
  KHÔNG có giao thông thời gian thực — hệ số giao thông ở đây là LUẬT theo khung giờ, không phải dữ liệu kẹt xe trực tiếp.
- Thời tiết hiện tại: Open-Meteo (miễn phí, không khoá) → hệ số phạt thời tiết theo lượng mưa / dông / gió.

Nguyên tắc: tín hiệu chỉ là thông tin MỀM (hiển thị + cảnh báo), không đổi hard gate. Mọi lỗi mạng/timeout/dữ liệu sai → trả None,
ETA tự hạ về luật và UI ghi rõ nguồn nào không có (không bịa số). Tham số có version `eta-signals-v1`.
"""
import time
from datetime import datetime, timedelta
from threading import Lock

import httpx

from ..config import settings
from ..tracking import geo
from . import baseline

VERSION = "eta-signals-v1"
PARAMS = {
    "truck_factor": 1.25,        # xe tải chậm hơn thời gian lái xe con của OSRM (profile car)
    "traffic_factor": {"night": 0.95, "normal": 1.0, "peak_am": 1.3, "peak_pm": 1.35},  # LUẬT theo khung giờ, không phải kẹt xe trực tiếp
    "rain_mm_h": [(0.2, 1.0), (2.5, 1.05), (7.6, 1.15), (float("inf"), 1.30)],          # (ngưỡng trên, hệ số)
    "thunder_min_factor": 1.30,  # WMO code >= 95 (dông)
    "wind_kmh_threshold": 50.0, "wind_extra": 0.05,
    "p90_extra_weather": 0.5,    # phần hệ số thời tiết (vượt 1.0) được nhân thêm vào độ rộng P90 khi thời tiết xấu
    "max_points": 400,           # giới hạn số điểm hình học lưu/trả về
}
_ROUTE_TTL, _WEATHER_TTL, _FAIL_TTL = 24 * 3600, 600, 60
_cache: dict[str, tuple[float, object]] = {}
_lock = Lock()
_health: dict[str, dict] = {"osrm": {"ok": None, "at": None, "error": None}, "weather": {"ok": None, "at": None, "error": None}}


def enabled() -> bool:
    return settings.signals_enabled


def health() -> dict:
    return {k: dict(v) for k, v in _health.items()}


def _mark(source: str, ok: bool, error: str | None = None) -> None:
    _health[source] = {"ok": ok, "at": time.time(), "error": error}


def _get_json(url: str, params: dict | None = None) -> dict:
    """Điểm duy nhất gọi mạng (test thay thế hàm này). Timeout ngắn để không treo request của người dùng."""
    r = httpx.get(url, params=params, timeout=settings.signals_timeout_s, headers={"User-Agent": "logection-eta/1.0"})
    r.raise_for_status()
    return r.json()


def _cached(key: str, ttl: float, fetch):
    """Cache trong bộ nhớ + cache âm (lỗi nhớ 60 giây để không dồn dập gọi lại khi dịch vụ đang chết)."""
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        value = fetch()
        exp = now + ttl
    except Exception:  # noqa: BLE001 — mọi lỗi mạng/định dạng đều hạ về luật
        value, exp = None, now + _FAIL_TTL
    with _lock:
        _cache[key] = (exp, value)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ------------------------------------------------------------------ tuyến đường bộ (OSRM)
def _thin(pts: list[geo.Point], keep: set[int], limit: int) -> tuple[list[geo.Point], dict[int, int]]:
    """Giảm số điểm nhưng luôn giữ điểm đầu/cuối/điểm lấy hàng. Trả (điểm mới, ánh xạ chỉ số cũ→mới của các điểm giữ)."""
    if len(pts) <= limit:
        return pts, {i: i for i in keep}
    stride = -(-len(pts) // limit)
    idx = sorted({i for i in range(0, len(pts), stride)} | keep | {len(pts) - 1})
    return [pts[i] for i in idx], {i: idx.index(i) for i in keep}


def fetch_road_route(start: geo.Point, pickup: geo.Point, dest: geo.Point) -> dict | None:
    """Tuyến đường bộ thật xe → điểm lấy → ICD. None nếu tắt/lỗi. Kết quả:
    {points: [(lat,lng)], pickup_index, distance_km, duration_min, leg_minutes: [..], source}."""
    if not enabled():
        return None
    direct = geo.haversine_km(start, pickup) <= 0.05  # xe đã ở điểm lấy: chỉ cần 2 điểm
    wps = [pickup, dest] if direct else [start, pickup, dest]
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in wps)

    def fetch():
        data = _get_json(f"{settings.osrm_url.rstrip('/')}/route/v1/driving/{coords}", {"overview": "full", "geometries": "geojson", "steps": "false"})
        if data.get("code") != "Ok" or not data.get("routes"):
            raise ValueError("OSRM: no route")
        r = data["routes"][0]
        pts = [(c[1], c[0]) for c in r["geometry"]["coordinates"]]
        if len(pts) < 2:
            raise ValueError("OSRM: empty geometry")
        legs = r["legs"]
        pk = 0 if direct else min(range(len(pts)), key=lambda i: geo.haversine_km(pts[i], pickup))  # điểm hình học gần điểm lấy nhất
        thin, mp = _thin(pts, {pk, len(pts) - 1}, PARAMS["max_points"])
        return {"points": thin, "pickup_index": mp[pk], "distance_km": round(r["distance"] / 1000, 2), "duration_min": round(r["duration"] / 60, 1),
                "leg_minutes": [round(lg["duration"] / 60, 1) for lg in legs], "source": "osrm"}

    out = _cached(f"route:{coords}", _ROUTE_TTL, fetch)
    _mark("osrm", out is not None, None if out else "unavailable")
    return out


# ------------------------------------------------------------------ thời tiết (Open-Meteo)
def fetch_weather(lat: float, lng: float) -> dict | None:
    """Thời tiết hiện tại tại (lat,lng), làm tròn 0,05° để dùng chung cache. None nếu tắt/lỗi."""
    if not enabled():
        return None
    la, ln = round(lat * 20) / 20, round(lng * 20) / 20

    def fetch():
        d = _get_json(settings.weather_url, {"latitude": la, "longitude": ln, "current": "precipitation,weather_code,wind_speed_10m", "timezone": "UTC"})
        c = d["current"]
        return {"precip_mm_h": float(c["precipitation"]), "weather_code": int(c["weather_code"]), "wind_kmh": float(c["wind_speed_10m"]),
                "observed_at": c.get("time"), "source": "open-meteo"}

    out = _cached(f"wx:{la}:{ln}", _WEATHER_TTL, fetch)
    _mark("weather", out is not None, None if out else "unavailable")
    return out


def weather_factor(w: dict | None) -> float:
    """Hệ số phạt thời tiết ≥ 1.0 (1.0 nếu không có dữ liệu — không bịa phạt)."""
    if not w:
        return 1.0
    f = next(factor for limit, factor in PARAMS["rain_mm_h"] if w["precip_mm_h"] < limit)
    if w["weather_code"] >= 95:
        f = max(f, PARAMS["thunder_min_factor"])
    if w["wind_kmh"] >= PARAMS["wind_kmh_threshold"]:
        f += PARAMS["wind_extra"]
    return round(f, 3)


# ------------------------------------------------------------------ ETA điều chỉnh
def adjusted_minutes(free_flow_min: float, band: str, wx_factor: float) -> dict:
    """P50/P90 (phút) từ thời gian lái thông thoáng × hệ số xe tải × hệ số khung giờ × hệ số thời tiết."""
    cfg = PARAMS
    p50 = free_flow_min * cfg["truck_factor"] * cfg["traffic_factor"][band] * wx_factor
    spread = 0.15 + (wx_factor - 1.0) * cfg["p90_extra_weather"] + {"night": 0.0, "normal": 0.1, "peak_am": 0.25, "peak_pm": 0.3}[band]
    return {"p50": round(p50, 1), "p90": round(p50 * (1 + spread) + 10, 1)}


def estimate(road: dict | None, weather: dict | None, remaining_fraction: float, now: datetime, params: dict) -> dict:
    """ETA có tín hiệu thật cho phần quãng đường còn lại. Thiếu tuyến → status 'fallback' (không có p50/p90, UI dùng ETA luật)."""
    band = baseline.band_for(now, params)
    out = {"method": "rule-based+signals", "version": VERSION, "band": band, "sources": {"route": road["source"] if road else None,
           "weather": weather["source"] if weather else None}, "simulated_positions": True}
    if not road:
        return {**out, "status": "fallback", "reason": "road_route_unavailable", "confidence": "low (rule-based)", "p50": None, "p90": None}
    wf = weather_factor(weather)
    mins = adjusted_minutes(road["duration_min"] * max(remaining_fraction, 0.0), band, wf)
    status = "ok" if weather else "partial"  # partial: có tuyến thật nhưng thiếu thời tiết
    return {**out, "status": status, "confidence": "medium" if weather else "low-medium", "p50": (now + timedelta(minutes=mins["p50"])).isoformat(),
            "p90": (now + timedelta(minutes=mins["p90"])).isoformat(), "minutes_p50": mins["p50"], "minutes_p90": mins["p90"],
            "components": {"road_km": road["distance_km"], "free_flow_min": road["duration_min"], "remaining_fraction": round(remaining_fraction, 3),
                           "truck_factor": PARAMS["truck_factor"], "traffic_factor": PARAMS["traffic_factor"][band], "weather_factor": wf},
            "weather": weather}
