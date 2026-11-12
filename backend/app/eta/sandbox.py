"""ETA Sandbox — công cụ NỘI BỘ để team tự thử và tinh chỉnh ETA trước khi chốt demo. Không phải tính năng cho người dùng cuối.

Lớp MỎNG: chỉ gọi lại đúng các hàm đã có (`ml.train`, `compare.rule_vs_ml` → `baseline.interval` + `ml.predict`, `signals.fetch_*`)
và tổng hợp kết quả thành bảng. KHÔNG tính lại luật, không huấn luyện riêng, không tự gọi API theo cách khác.
Không đổi hard gate; tín hiệu thật vẫn chỉ là tầng MỀM. Dữ liệu huấn luyện vẫn là lịch sử MÔ PHỎNG (chỉ chứng minh pipeline).

Lưu ý: `sweep_drift` chạy trên pipeline scikit-learn MÔ PHỎNG (`ml.train`), không phải model ONNX; `scenario_matrix` đi qua `ml.predict` nên phản ánh model ONNX (kèm cổng promote) khi có.
Lưu ý vận hành: `sweep_drift` huấn luyện lại mô hình DÙNG CHUNG của tiến trình rồi KHÔI PHỤC đúng trạng thái cũ khi xong; trong lúc chạy
(vài giây) các dự báo ML khác trong cùng tiến trình có thể thấy trạng thái tạm. Vì vậy chỉ dùng trong lúc phát triển/chuẩn bị demo.
"""
import threading
import time
from datetime import date, datetime, timedelta, timezone

from ..config import settings
from . import baseline, compare, ml, signals

DEFAULT_DRIFTS = (0.0, 0.05, 0.1, 0.15, 0.2, 0.3)
BANDS = ("peak_am", "peak_pm", "night", "normal")
REFERENCE_DAY = date(2026, 11, 11)  # một ngày thường cố định để bảng kịch bản tái lập được
# điểm mẫu cố định (trùng toạ độ địa điểm seed): xe (Depot Thủ Đức) → điểm lấy (KCN Sóng Thần) → ICD
DEFAULT_POINTS: tuple[tuple[float, float], ...] = ((10.87, 106.77), (10.90, 106.74), (10.85, 106.80))

_run_lock = threading.Lock()  # các lượt sandbox chạy lần lượt (không chồng nhau)


def default_params() -> dict:
    """Bộ giả định mặc định (assume-v2) — để CLI chạy KHÔNG cần DB. Endpoint truyền bộ đang hiệu lực trong DB."""
    from ..seed import ASSUMPTIONS_V1
    return ASSUMPTIONS_V1


# ------------------------------------------------------------------ 1. quét độ trôi
def sweep_drift(drifts: list[float] | tuple[float, ...] | None = None, params: dict | None = None) -> list[dict]:
    """Huấn luyện lại theo từng độ trôi (`ml.train`) → bảng cho thấy ở ngưỡng nào mô hình tự hạ về luật. Khôi phục trạng thái mô hình cũ sau khi chạy."""
    params = params or default_params()
    rows: list[dict] = []
    with _run_lock:
        with ml._lock:  # chụp trạng thái hiện tại (kể cả đối tượng mô hình) để trả lại nguyên vẹn
            saved = dict(ml._state)
        try:
            for d in (DEFAULT_DRIFTS if drifts is None else drifts):
                info = ml.train(params["transit_minutes"], float(d))
                x = info["metrics"] or {}
                rows.append({"drift": float(d), "promoted": info["status"] == "promoted", "mae_rule": x.get("mae_rule"), "mae_ml": x.get("mae_ml"),
                             "improvement_pct": x.get("improvement_pct"), "p90_coverage_ml": x.get("p90_coverage_ml"),
                             "status": info["status"], "reason": info["reason"]})
        finally:
            with ml._lock:
                ml._state.clear()
                ml._state.update(saved)
    return rows


# ------------------------------------------------------------------ 2. lưới kịch bản theo khung giờ
def _hour_for(band: str, params: dict) -> int:
    """Một giờ (giờ vận hành) rơi vào `band` — hỏi chính `baseline.band_for` chứ không lặp lại luật khung giờ."""
    tz = timezone(timedelta(hours=params["eta"]["tz_offset_hours"]))
    for h in range(24):
        if baseline.band_for(datetime(REFERENCE_DAY.year, REFERENCE_DAY.month, REFERENCE_DAY.day, h, tzinfo=tz), params) == band:
            return h
    raise ValueError(f"no hour maps to band {band}")


def scenario_matrix(params: dict | None = None, km: float = ml.BASE_KM) -> list[dict]:
    """Mỗi khung giờ: P50/P90 (phút trung chuyển) của luật và của ML + bên nào đang được dùng — qua `compare.rule_vs_ml` (cùng đường với /v1/eta/predict)."""
    params = params or default_params()
    ml.ensure_trained(params["transit_minutes"])
    tz = timezone(timedelta(hours=params["eta"]["tz_offset_hours"]))
    rows = []
    for band in BANDS:
        h = _hour_for(band, params)
        depart = datetime(REFERENCE_DAY.year, REFERENCE_DAY.month, REFERENCE_DAY.day, h, tzinfo=tz).astimezone(timezone.utc)
        out = compare.rule_vs_ml(params, depart, km)
        rule, pred = out["rule"], out["ml"]
        rows.append({"band": band, "depart_hour": h, "km": km, "rule_p50": rule["minutes_p50"],
                     "rule_p90": round((datetime.fromisoformat(rule["p90"]) - depart).total_seconds() / 60),
                     "ml_p50": pred["p50_minutes"] if pred else None, "ml_p90": pred["p90_minutes"] if pred else None,
                     "used": out["used"], "model_status": out["status"]})
    return rows


# ------------------------------------------------------------------ 3. kiểm tra sức khoẻ tín hiệu thật
def _probe(fn, *args) -> tuple[object | None, int, str | None]:
    t0 = time.perf_counter()
    try:
        out, err = fn(*args), None
    except Exception as e:  # noqa: BLE001 — sandbox không được sập vì một nguồn lỗi
        out, err = None, f"{type(e).__name__}"
    return out, round((time.perf_counter() - t0) * 1000), err


def signals_health_check(sample_points: list[tuple[float, float]] | None = None, fresh: bool = False) -> dict:
    """Gọi TRỰC TIẾP `signals.fetch_road_route / fetch_weather / fetch_traffic` với 3 điểm mẫu (xe, điểm lấy, ICD) — không cần chuyến đang chạy.
    `fresh=True` xoá cache tín hiệu trước (thấy ngay trạng thái thật; tốn thêm hạn mức API, nhất là Mapbox). Mặc định có thể trả kết quả đã cache
    (lỗi được nhớ 60 giây). Trạng thái mỗi nguồn: ok | error | disabled | not_configured (chỉ Mapbox)."""
    pts = list(sample_points) if sample_points else list(DEFAULT_POINTS)
    if len(pts) < 3:
        raise ValueError("sample_points needs 3 points: vehicle, pickup, destination")
    start, pickup, dest = pts[0], pts[1], pts[2]
    configured = bool(settings.mapbox_token)  # chỉ báo có/không — không bao giờ trả khoá ra ngoài
    if not signals.enabled():  # tắt toàn bộ: không gọi mạng
        return {"enabled": False, "osrm": {"status": "disabled"}, "weather": {"status": "disabled"}, "mapbox_configured": configured,
                "mapbox": {"status": "disabled"}, "health": signals.health(), "sample_points": pts, "is_simulated_positions": True}
    with _run_lock:
        if fresh:
            signals.clear_cache()
        route, ms_r, err_r = _probe(signals.fetch_road_route, start, pickup, dest)
        wx, ms_w, err_w = _probe(signals.fetch_weather, pickup[0], pickup[1])
        osrm = {"status": "ok" if route else "error", "latency_ms": ms_r, "distance_km": route["distance_km"] if route else None,
                "duration_min": route["duration_min"] if route else None, **({"error": err_r} if err_r else {})}
        weather = {"status": "ok" if wx else "error", "latency_ms": ms_w, "precip_mm_h": wx["precip_mm_h"] if wx else None,
                   "weather_code": wx["weather_code"] if wx else None, **({"error": err_w} if err_w else {})}
        if not configured:
            mapbox: dict = {"status": "not_configured"}
        else:
            tr, ms_t, err_t = _probe(signals.fetch_traffic, [start, pickup, dest])
            mapbox = {"status": "ok" if tr else "error", "latency_ms": ms_t, "live_min": tr["live_min"] if tr else None,
                      "typical_min": tr["typical_min"] if tr else None, **({"error": err_t} if err_t else {})}
    return {"enabled": True, "osrm": osrm, "weather": weather, "mapbox_configured": configured, "mapbox": mapbox,
            "health": signals.health(), "sample_points": pts, "is_simulated_positions": True}
