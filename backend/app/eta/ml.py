"""ETA học máy (scikit-learn) trên LỊCH SỬ MÔ PHỎNG — chỉ chứng minh PIPELINE, không phải độ chính xác thật.

- Lịch sử sinh xác định (seed cố định): km, giờ, thứ, thời tiết MÔ PHỎNG, ồn ngẫu nhiên, và một đoạn "trôi" (drift) ở cuối.
- Chia THEO THỜI GIAN (train → test, không xáo trộn): không rò rỉ tương lai vào huấn luyện.
- Hai mô hình phân vị (P50, P90) GradientBoostingRegressor; so với baseline luật (transit cố định).
- Chỉ "promote" (dùng thay luật) khi MAE giảm ≥ 15% VÀ độ phủ P90 trong [0.85, 0.97]; ngược lại tự hạ về ETA luật.
- Mô hình giữ trong bộ nhớ tiến trình, dựng lại xác định khi cần (không lưu blob/pickle).
"""
import threading
from datetime import datetime, timedelta, timezone

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

DEFAULT_DRIFT = 0.0  # mặc định không trôi (mô hình được promote); chèn trôi (vd 0.15) để xem mô hình tự hạ về luật
SEED = 20261111
N_TRIPS = 3000
TEST_FRACTION = 0.3
MIN_IMPROVEMENT = 0.15
COVERAGE_RANGE = (0.85, 0.97)
BASE_KM = 26.0
LABEL = "ml-sim-v1"

_lock = threading.Lock()
_state: dict = {"trained": False}


def sim_weather(day: int, hour: int) -> int:
    """Thời tiết MÔ PHỎNG xác định (1 = mưa). Cùng hàm dùng cho huấn luyện và dự báo."""
    return 1 if (day * 31 + hour * 17) % 10 < 2 else 0


def _band_mult(hour: int) -> float:
    return 1.3 if hour in (7, 8, 16, 17, 18) else (0.88 if hour in (22, 23, 0, 1, 2, 3, 4, 5) else 1.0)


def _features(km, hour, weekday, rain):
    return np.column_stack([km, hour, weekday, rain]).astype(float)


def simulate_history(transit_minutes: float, drift: float = DEFAULT_DRIFT, n: int = N_TRIPS, seed: int = SEED):
    """Trả (X, y, t_index). y = phút trung chuyển thực tế mô phỏng. 30% cuối có drift (tắc hơn `drift`, mặc định 0)."""
    rng = np.random.default_rng(seed)
    km = rng.normal(BASE_KM, 3.0, n).clip(15, 40)
    hour = rng.integers(0, 24, n)
    weekday = rng.integers(0, 7, n)
    day = np.arange(n) // 24 + 1
    rain = np.array([sim_weather(int(d), int(h)) for d, h in zip(day, hour)])
    mult = np.array([_band_mult(int(h)) for h in hour]) * (1 + 0.18 * rain) * np.where(weekday >= 5, 0.93, 1.0)
    y = transit_minutes * (km / BASE_KM) * mult * (1 + rng.normal(0, 0.07, n))
    y = np.where(np.arange(n) >= int(n * (1 - TEST_FRACTION)), y * (1 + drift), y)  # drift ở đoạn cuối
    return _features(km, hour, weekday, rain), y, np.arange(n)


def train(transit_minutes: float = 90.0, drift: float = DEFAULT_DRIFT) -> dict:
    with _lock:
        X, y, _ = simulate_history(transit_minutes, drift)
        cut = int(len(y) * (1 - TEST_FRACTION))  # chia theo thời gian: [fit | hiệu chỉnh | test]
        fit_end = int(cut * 0.85)
        Xtr, ytr, Xcal, ycal, Xte, yte = X[:fit_end], y[:fit_end], X[fit_end:cut], y[fit_end:cut], X[cut:], y[cut:]
        m50 = GradientBoostingRegressor(loss="quantile", alpha=0.5, n_estimators=120, max_depth=3, random_state=SEED).fit(Xtr, ytr)
        m90 = GradientBoostingRegressor(loss="quantile", alpha=0.9, n_estimators=120, max_depth=3, random_state=SEED).fit(Xtr, ytr)
        offset = float(np.quantile(ycal - m90.predict(Xcal), 0.9))  # hiệu chỉnh P90 trên đoạn hiệu chỉnh (không đụng test)
        p50, p90 = m50.predict(Xte), np.maximum(m90.predict(Xte) + offset, m50.predict(Xte))
        rule50 = np.full_like(yte, transit_minutes)
        rule90 = rule50 * 1.25 + 10  # P90 luật điển hình (khung giờ thường + đệm)
        mae = lambda p: float(np.mean(np.abs(p - yte)))  # noqa: E731
        within = lambda p: float(np.mean(np.abs(p - yte) <= 15))  # noqa: E731
        improvement = 1 - mae(p50) / mae(rule50)
        cover = float(np.mean(yte <= p90))
        promoted = improvement >= MIN_IMPROVEMENT and COVERAGE_RANGE[0] <= cover <= COVERAGE_RANGE[1]
        _state.update({
            "trained": True, "m50": m50, "m90": m90, "p90_offset": offset, "transit_minutes": transit_minutes, "promoted": promoted,
            "metrics": {
                "n_train": int(fit_end), "n_calibration": int(cut - fit_end), "n_test": int(len(yte)), "split": "time-ordered (train earlier, test later; optional injected drift in the last 30%)",
                "mae_rule": round(mae(rule50), 1), "mae_ml": round(mae(p50), 1), "improvement_pct": round(100 * improvement, 1),
                "within15_rule": round(within(rule50), 3), "within15_ml": round(within(p50), 3),
                "p90_coverage_rule": round(float(np.mean(yte <= rule90)), 3), "p90_coverage_ml": round(cover, 3),
                "min_improvement_pct": int(MIN_IMPROVEMENT * 100), "coverage_target": list(COVERAGE_RANGE), "drift": drift,
            },
            "status": "promoted" if promoted else "rule_fallback",
            "reason": "ok" if promoted else ("improvement_below_threshold" if improvement < MIN_IMPROVEMENT else "p90_coverage_out_of_range"),
        })
        return model_info()


def ensure_trained(transit_minutes: float = 90.0) -> None:
    if not _state.get("trained"):
        try:
            train(transit_minutes)
        except Exception:  # noqa: BLE001 — lỗi huấn luyện không được làm sập app: dùng ETA luật
            _state.update({"trained": False, "status": "rule_fallback", "reason": "training_error"})


def model_info() -> dict:
    return {"label": LABEL, "is_simulated_history": True, "trained": bool(_state.get("trained")), "status": _state.get("status", "untrained"),
            "reason": _state.get("reason", "not_trained"), "metrics": _state.get("metrics"),
            "note": "Dữ liệu lịch sử MÔ PHỎNG — chỉ chứng minh pipeline, chưa chứng minh độ chính xác thật."}


def predict(depart_at: datetime, km: float = BASE_KM) -> dict | None:
    """(P50, P90) phút trung chuyển nếu mô hình đã được promote; None → dùng ETA luật. Mọi lỗi → None (tự hạ về luật)."""
    if not _state.get("promoted"):
        return None
    try:
        local = depart_at.astimezone(timezone(timedelta(hours=7)))
        day = local.toordinal() % 100000
        x = _features([km], [local.hour], [local.weekday()], [sim_weather(day, local.hour)])
        p50 = float(_state["m50"].predict(x)[0]); p90 = max(float(_state["m90"].predict(x)[0]) + _state["p90_offset"], p50)
        return {"p50_minutes": round(p50), "p90_minutes": round(p90), "method": "ml-sim", "label": LABEL, "confidence": "low (simulated history)"}
    except Exception:  # noqa: BLE001
        return None
