"""Sinh dữ liệu ETA MÔ PHỎNG để huấn luyện ngoài (Kaggle) — theo đặc tả `docs/ETA_DATASET_SPEC.md`.

  python -m app.eta_data_gen [--out ../data/eta] [--trips-per-day 59] [--no-drift]

Ra 4 file: eta_trips.csv, eta_schema.json, eta_generator_params.json, ETA_TRAINING_GUIDE.md. Hạt giống cố định → sinh lại ra đúng file cũ.
⚠️ Dữ liệu 100% MÔ PHỎNG: mô hình học trên đó chỉ chứng minh QUY TRÌNH (chia theo thời gian, cổng promote, tự hạ về luật), KHÔNG chứng minh
độ chính xác ngoài đời (DRAFT 6.2). Chỉ cần numpy (không pandas).
"""
import csv
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

SEED = 20261111
TZ = timezone(timedelta(hours=7))
START, END = date(2025, 11, 1), date(2026, 10, 31)
CALIB_FROM, TEST_FROM = date(2026, 7, 1), date(2026, 9, 1)  # train < 07-01 · calib 07-01..08-31 · test ≥ 09-01 (có drift)
MODEL_VERSION = "eta-onnx-sim-v1"

# khung giờ: cùng định nghĩa với app/eta/baseline.py (peak_am 7–8h, peak_pm 16–18h, night 22–5h) — test kiểm tra khớp
HOURS = {"peak_am": [7, 8], "peak_pm": [16, 17, 18], "night": [22, 23, 0, 1, 2, 3, 4, 5]}
BANDS = ("night", "normal", "peak_am", "peak_pm")

PARAMS = {
    "seed": SEED, "model_version": MODEL_VERSION, "period": [START.isoformat(), END.isoformat()],
    "split": {"calib_from": CALIB_FROM.isoformat(), "test_from": TEST_FROM.isoformat()},
    "trips_per_day": 59, "weekend_volume_factor": 0.7,
    "hour_weight": {"night": 0.25, "normal": 1.0, "peak_am": 1.3, "peak_pm": 1.3},
    "routes": {"KCN_A_ICD": {"p": 0.55, "distance_mean": 22.0, "distance_sd": 4.5, "time_factor": 1.00},
               "KCN_B_ICD": {"p": 0.45, "distance_mean": 28.0, "distance_sd": 5.5, "time_factor": 1.06}},
    "distance_clip_km": [8.0, 40.0],
    "vehicle_class": {"heavy": {"p": 0.4, "time_factor": 1.12}, "medium": {"p": 0.4, "time_factor": 1.00}, "light": {"p": 0.2, "time_factor": 0.93}},
    "effective_speed_kmh": {"night": 26.0, "normal": 19.5, "peak_am": 13.5, "peak_pm": 12.5},  # ĐÃ GỒM dừng/xếp hàng; thấp để khớp giả định 90' cho ~26 km
    "weekend_time_factor": 0.93,
    "rain": {"p_wet_season": 0.22, "p_dry_season": 0.05, "wet_months": [5, 6, 7, 8, 9, 10], "afternoon_boost": 1.6, "afternoon_hours": [13, 14, 15, 16, 17, 18],
             "mean_mm_h": 4.0, "max_mm_h": 30.0, "time_slope_per_mm": 0.018, "time_factor_cap": 1.35},
    "wind": {"gamma_shape": 2.2, "gamma_scale": 4.0, "rain_bonus_kmh": 6.0, "max_kmh": 60.0, "strong_from_kmh": 50.0, "strong_extra": 0.04},
    "month_factor": {"10": 1.06, "11": 1.06, "12": 1.06, "2": 0.95},
    "noise_sigma": {"night": 0.08, "normal": 0.11, "peak_am": 0.15, "peak_pm": 0.16},  # lognormal → lệch phải
    "gate_queue_mean_min": {"night": 6.0, "normal": 6.0, "peak_am": 6.0, "peak_pm": 14.0},
    "incident": {"p": 0.025, "p_drift": 0.04, "delay_min_uniform": [20, 90]},
    "drift": {"from": TEST_FROM.isoformat(), "time_factor": 1.08, "note": "2 tháng cuối (test): giao thông chậm hơn 8% + sự cố 4% — để kiểm tra cổng phát hiện trôi"},
    # bảng luật "đã duyệt" (ước lượng thô của người vận hành): CỐ Ý lệch ~+10% (lạc quan) so với tốc độ sinh dữ liệu, nên baseline mạnh nhưng không hoàn hảo
    "rule_dist": {"speed_kmh": {"night": 28.0, "normal": 21.5, "peak_am": 15.0, "peak_pm": 14.0},
                  "p90_spread": {"night": 0.10, "normal": 0.15, "peak_am": 0.35, "peak_pm": 0.45}, "p90_buffer_min": 10.0},  # P90 như baseline.p90_extra_minutes
    "rule_const_min": 90.0,
}

NUMERIC = ["distance_km", "hour", "weekday", "is_weekend", "month", "rain_mm_h", "wind_kmh"]
ROUTES = list(PARAMS["routes"])
VEHICLES = list(PARAMS["vehicle_class"])
INPUT_ORDER = NUMERIC + [f"route_id={r}" for r in ROUTES] + [f"vehicle_class={v}" for v in VEHICLES]
COLUMNS = ["trip_id", "depart_at", "split", *NUMERIC, "route_id", "vehicle_class", "band", "actual_transit_min",
           "rule_const_min", "rule_dist_min", "baseline_median_min", "rule_dist_p90_min",
           "gate_queue_min", "had_incident", "incident_delay_min", "scenario_tag"]
FORBIDDEN_AS_FEATURES = ["trip_id", "depart_at", "split", "band", "actual_transit_min", "rule_const_min", "rule_dist_min", "baseline_median_min",
                         "rule_dist_p90_min", "gate_queue_min", "had_incident", "incident_delay_min", "scenario_tag"]


def band_of(hour: int) -> str:
    for b, hs in HOURS.items():
        if hour in hs:
            return b
    return "normal"


def _band_idx(hours: np.ndarray) -> np.ndarray:
    return np.array([BANDS.index(band_of(int(h))) for h in hours])


def generate(trips_per_day: int | None = None, drift: bool = True) -> list[dict]:
    """Trả danh sách dòng (dict) đã sắp theo thời gian, đủ cột như COLUMNS. `drift=False`: không có độ trôi ở 2 tháng cuối
    (mô hình dễ qua cổng promote hơn; dùng khi muốn có model "được dùng" để demo)."""
    P = json.loads(json.dumps(PARAMS))
    if not drift:
        P["drift"]["time_factor"], P["incident"]["p_drift"] = 1.0, P["incident"]["p"]
    rng = np.random.default_rng(P["seed"])
    n_day = trips_per_day or P["trips_per_day"]
    hw = np.array([P["hour_weight"][band_of(h)] for h in range(24)])
    hw = hw / hw.sum()

    stamps: list[datetime] = []
    d = START
    while d <= END:
        n = rng.poisson(n_day * (P["weekend_volume_factor"] if d.weekday() >= 5 else 1.0))
        hrs = rng.choice(24, size=n, p=hw)
        mins = rng.integers(0, 60, size=n)
        stamps += [datetime(d.year, d.month, d.day, int(h), int(m), tzinfo=TZ) for h, m in zip(hrs, mins)]
        d += timedelta(days=1)
    stamps.sort()
    N = len(stamps)

    hour = np.array([t.hour for t in stamps])
    weekday = np.array([t.weekday() for t in stamps])
    month = np.array([t.month for t in stamps])
    dates = [t.date() for t in stamps]
    in_drift = np.array([x >= TEST_FROM for x in dates])
    band_i = _band_idx(hour)

    # tuyến, quãng đường, xe
    route_i = rng.choice(len(ROUTES), size=N, p=[P["routes"][r]["p"] for r in ROUTES])
    dist = np.empty(N)
    for i, r in enumerate(ROUTES):
        m = route_i == i
        dist[m] = rng.normal(P["routes"][r]["distance_mean"], P["routes"][r]["distance_sd"], m.sum())
    dist = np.round(np.clip(dist, *P["distance_clip_km"]), 2)
    veh_i = rng.choice(len(VEHICLES), size=N, p=[P["vehicle_class"][v]["p"] for v in VEHICLES])

    # thời tiết mô phỏng (mùa mưa 5–10, chiều mưa nhiều hơn)
    wet = np.isin(month, P["rain"]["wet_months"])
    p_rain = np.where(wet, P["rain"]["p_wet_season"], P["rain"]["p_dry_season"]) * np.where(np.isin(hour, P["rain"]["afternoon_hours"]), P["rain"]["afternoon_boost"], 1.0)
    raining = rng.random(N) < np.clip(p_rain, 0, 0.95)
    rain = np.where(raining, np.clip(rng.exponential(P["rain"]["mean_mm_h"], N) + 0.2, 0.2, P["rain"]["max_mm_h"]), 0.0)
    wind = np.clip(rng.gamma(P["wind"]["gamma_shape"], P["wind"]["gamma_scale"], N) + np.where(raining, P["wind"]["rain_bonus_kmh"], 0.0), 0.0, P["wind"]["max_kmh"])
    rain, wind = np.round(rain, 1), np.round(wind, 1)

    # nhãn: thời gian chạy × nhiễu + chờ cổng + sự cố
    speed = np.array([P["effective_speed_kmh"][b] for b in BANDS])[band_i]
    f_veh = np.array([P["vehicle_class"][v]["time_factor"] for v in VEHICLES])[veh_i]
    f_route = np.array([P["routes"][r]["time_factor"] for r in ROUTES])[route_i]
    f_wkend = np.where(weekday >= 5, P["weekend_time_factor"], 1.0)
    f_rain = np.minimum(1 + P["rain"]["time_slope_per_mm"] * rain, P["rain"]["time_factor_cap"]) + np.where(wind >= P["wind"]["strong_from_kmh"], P["wind"]["strong_extra"], 0.0)
    f_month = np.array([P["month_factor"].get(str(m), 1.0) for m in month])
    f_drift = np.where(in_drift, P["drift"]["time_factor"], 1.0)
    run = dist / speed * 60 * f_veh * f_route * f_wkend * f_rain * f_month * f_drift
    sigma = np.array([P["noise_sigma"][b] for b in BANDS])[band_i]
    noise = rng.lognormal(0.0, sigma)
    queue = rng.exponential(np.array([P["gate_queue_mean_min"][b] for b in BANDS])[band_i])
    had_inc = rng.random(N) < np.where(in_drift, P["incident"]["p_drift"], P["incident"]["p"])
    inc_delay = np.where(had_inc, rng.uniform(*P["incident"]["delay_min_uniform"], N), 0.0)
    actual = np.round(np.maximum(run * noise + queue + inc_delay, 10.0), 1)

    # baseline luật (chỉ từ đặc trưng)
    rs = np.array([P["rule_dist"]["speed_kmh"][b] for b in BANDS])[band_i]
    rule_dist = dist / rs * 60
    spread = np.array([P["rule_dist"]["p90_spread"][b] for b in BANDS])[band_i]
    rule_p90 = rule_dist + rule_dist * spread + P["rule_dist"]["p90_buffer_min"]

    split = np.array(["train" if x < CALIB_FROM else "calib" if x < TEST_FROM else "test" for x in dates])
    # median theo (tuyến, khung giờ) — CHỈ trên tập train rồi gắn vào mọi dòng (không rò rỉ)
    med = {}
    overall = float(np.median(actual[split == "train"]))
    for ri in range(len(ROUTES)):
        for bi in range(len(BANDS)):
            m = (split == "train") & (route_i == ri) & (band_i == bi)
            med[(ri, bi)] = float(np.median(actual[m])) if m.sum() else overall

    rows = []
    for k in range(N):
        tag = "incident" if had_inc[k] else "drift" if (in_drift[k] and drift) else "normal"
        rows.append({
            "trip_id": k + 1, "depart_at": stamps[k].isoformat(), "split": str(split[k]),
            "distance_km": float(dist[k]), "hour": int(hour[k]), "weekday": int(weekday[k]), "is_weekend": int(weekday[k] >= 5), "month": int(month[k]),
            "rain_mm_h": float(rain[k]), "wind_kmh": float(wind[k]), "route_id": ROUTES[route_i[k]], "vehicle_class": VEHICLES[veh_i[k]],
            "band": BANDS[band_i[k]], "actual_transit_min": float(actual[k]),
            "rule_const_min": P["rule_const_min"], "rule_dist_min": round(float(rule_dist[k]), 1),
            "baseline_median_min": round(med[(int(route_i[k]), int(band_i[k]))], 1), "rule_dist_p90_min": round(float(rule_p90[k]), 1),
            "gate_queue_min": round(float(queue[k]), 1), "had_incident": int(had_inc[k]), "incident_delay_min": round(float(inc_delay[k]), 1), "scenario_tag": tag,
        })
    return rows


def schema(csv_sha256: str, n_rows: int) -> dict:
    return {
        "model_version": MODEL_VERSION, "is_simulated": True, "target": "actual_transit_min", "target_unit": "minutes",
        "prediction_time": "lúc xe rời điểm lấy hàng (depart_at)", "rows": n_rows, "csv_sha256": csv_sha256,
        "numeric_features": NUMERIC,
        "categorical_features": {"route_id": ROUTES, "vehicle_class": VEHICLES},
        "input_order": INPUT_ORDER, "input_dtype": "float32", "input_shape": ["N", len(INPUT_ORDER)],
        "output": {"shape": ["N", 2], "columns": ["p50_minutes", "p90_minutes"], "constraint": "p90 >= p50"},
        "valid_ranges": {"distance_km": PARAMS["distance_clip_km"], "hour": [0, 23], "weekday": [0, 6], "month": [1, 12], "rain_mm_h": [0, PARAMS["rain"]["max_mm_h"]],
                         "wind_kmh": [0, PARAMS["wind"]["max_kmh"]]},
        "forbidden_as_features": FORBIDDEN_AS_FEATURES,
        "splits": {"train": f"< {CALIB_FROM}", "calib": f"{CALIB_FROM} .. {TEST_FROM - timedelta(days=1)}", "test": f">= {TEST_FROM} (có drift)"},
        "promotion_gate": {"min_mae_improvement_pct": 15, "p90_coverage_range": [0.85, 0.97], "compare_against": "baseline mạnh nhất trong rule_const_min / rule_dist_min / baseline_median_min"},
        "columns": COLUMNS,
    }


GUIDE = """# Hướng dẫn huấn luyện ETA trên Kaggle (dữ liệu MÔ PHỎNG)

> ⚠️ Dữ liệu do bộ sinh tạo ra (`eta_generator_params.json`). Mô hình học lại chính công thức đó, nên kết quả **chỉ chứng minh quy trình**, không chứng minh
> độ chính xác ngoài đời. Khi trình bày hãy nhấn vào cơ chế (chia theo thời gian, cổng promote, tự hạ về luật), không phải con số.

## Các bước
1. Trên Kaggle: **Create → New Dataset**, tải lên `eta_trips.csv` và `eta_schema.json` (đặt tên dataset tuỳ ý, ví dụ `eta-sim`).
2. **Create → New Notebook** → *File → Import Notebook* → chọn `eta_train_kaggle.ipynb`. Bên phải: **Add Input** → chọn dataset vừa tạo.
3. Bật **Internet** (Settings) nếu notebook báo thiếu `onnx`/`onnxruntime` (ô đầu tiên sẽ tự cài). GPU **không cần** (dữ liệu nhỏ, CPU chạy vài chục giây).
4. **Run All**. Notebook tự: kiểm tra không rò rỉ → so baseline → huấn luyện P50/P90 → hiệu chỉnh P90 → đánh giá trên `test` → xuất ONNX → kiểm tra ONNX khớp PyTorch → ghi model card.
5. Tải 2 file ở `/kaggle/working/` về máy: **`eta_model.onnx`** và **`eta_model_card.json`**, rồi gửi lại.

## Kết quả mong đợi (để biết có chạy đúng không)
- Mô hình thắng `rule_const_min` (hằng số 90) rất rõ; thắng `rule_dist_min`/`baseline_median_min` ít hơn.
- Do **drift cố ý** ở 2 tháng cuối, độ phủ P90 trên `test` thường **thấp hơn** trên `calib`; có thể rơi ra ngoài [0,85; 0,97] → cổng promote báo "hạ về luật". Đây là hành vi **đúng và có chủ đích** (minh hoạ cổng phát hiện trôi), không phải lỗi.

## Hợp đồng đầu vào/đầu ra của model (backend sẽ dựa vào đây)
- Đầu vào `features`: `float32 [N, 12]`, thứ tự cột = `input_order` trong `eta_schema.json` (chuẩn hoá đã **nhúng trong ONNX**).
- Đầu ra `eta`: `float32 [N, 2]` = (`p50_minutes`, `p90_minutes`), bảo đảm `p90 >= p50`.
"""


def write_all(out: Path, trips_per_day: int | None = None, drift: bool = True) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rows = generate(trips_per_day, drift)
    csv_path = out / "eta_trips.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    (out / "eta_schema.json").write_text(json.dumps(schema(sha, len(rows)), ensure_ascii=False, indent=2), encoding="utf-8")
    used = json.loads(json.dumps(PARAMS))
    if not drift:
        used["drift"].update(time_factor=1.0, note="KHÔNG có drift (--no-drift)")
        used["incident"]["p_drift"] = used["incident"]["p"]
    (out / "eta_generator_params.json").write_text(json.dumps(used, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "ETA_TRAINING_GUIDE.md").write_text(GUIDE, encoding="utf-8")
    return {"rows": len(rows), "sha256": sha, "dir": str(out)}


def summary(rows: list[dict]) -> str:
    a = np.array([r["actual_transit_min"] for r in rows])
    out = [f"{len(rows)} chuyến · {rows[0]['depart_at'][:10]} → {rows[-1]['depart_at'][:10]}"]
    for s in ("train", "calib", "test"):
        out.append(f"  {s:5s}: {sum(r['split'] == s for r in rows):6d} chuyến")
    near = [r["actual_transit_min"] for r in rows if 25 <= r["distance_km"] <= 27 and r["band"] == "normal" and r["split"] == "train"]
    out.append(f"trung vị nhãn: toàn bộ {np.median(a):.1f}′ · quãng 25–27 km, giờ thường (train) {np.median(near):.1f}′ (giả định hệ thống: 90′)")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("../data/eta")
    tpd = int(argv[argv.index("--trips-per-day") + 1]) if "--trips-per-day" in argv else None
    drift = "--no-drift" not in argv
    info = write_all(out, tpd, drift)
    print(summary(generate(tpd, drift)) + ("" if drift else "\n(không có drift)"))
    print(f"→ đã ghi 4 file vào {info['dir']}  (eta_trips.csv sha256 {info['sha256'][:16]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
