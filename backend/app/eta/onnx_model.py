"""Mô hình ETA ONNX huấn luyện NGOÀI (Kaggle) trên dữ liệu MÔ PHỎNG — nạp, kiểm tra và dự báo; mọi lỗi → hạ về ETA luật.

Thư mục model (mặc định `backend/model/`, đổi bằng PIVOT_ETA_MODEL_DIR, đặt rỗng để TẮT): `eta_model.onnx` + `eta_model_card.json`.
Nguyên tắc (CLAUDE.md mục 1, 6, 7; DRAFT 6.2):
- Chỉ nạp khi **mã băm** khớp model card và `feature_order` khớp hợp đồng của backend; đầu ra phải đúng hình dạng. Sai một điều → KHÔNG dùng (reason rõ).
- **Cổng promote** lấy từ số đo trên tập test trong model card (giảm MAE ≥ 15% so với baseline mạnh nhất VÀ độ phủ P90 ∈ [0,85; 0,97]); không đạt → `rule_fallback`.
  `PIVOT_ETA_MODEL_FORCE=true` cho phép dùng dù cổng không đạt, CHỈ để thử/demo, luôn gắn nhãn "bật thủ công".
- Đầu vào ngoài `valid_ranges`, thiếu tuyến/hạng xe của chuyến thật, hoặc lỗi khi chạy → trả None (dùng ETA luật). Không bao giờ ném lỗi.
- Hard gate KHÔNG dùng model này (vẫn là P50 của ETA luật); đây chỉ là thông tin tham khảo + cảnh báo mềm. Dữ liệu huấn luyện là MÔ PHỎNG.
"""
import hashlib
import json
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import settings

EXPECTED_ORDER = ["distance_km", "hour", "weekday", "is_weekend", "month", "rain_mm_h", "wind_kmh",
                  "route_id=KCN_A_ICD", "route_id=KCN_B_ICD", "vehicle_class=heavy", "vehicle_class=medium", "vehicle_class=light"]
ROUTES = ("KCN_A_ICD", "KCN_B_ICD")
VEHICLES = ("heavy", "medium", "light")
DEFAULT_CTX = {"route_id": "KCN_A_ICD", "vehicle_class": "medium", "rain_mm_h": 0.0, "wind_kmh": 0.0}  # chỉ cho what-if/sandbox; ghi vào `assumed`
ROUTE_BY_ORIGIN = (("song than", "KCN_A_ICD"), ("vsip", "KCN_B_ICD"))  # theo tên điểm lấy hàng trong seed (không dấu, chữ thường)
LABEL_FALLBACK = "eta-onnx"
TZ = timezone(timedelta(hours=7))
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "model"

_lock = threading.Lock()
_state: dict | None = None


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D")) if unicodedata.category(c) != "Mn").lower()


def route_id_for(origin_name: str | None) -> str | None:
    """Tuyến của lô theo tên điểm lấy hàng; không nhận ra → None (không đoán)."""
    n = _fold(origin_name or "")
    return next((r for hint, r in ROUTE_BY_ORIGIN if hint in n), None)


def vehicle_class_for(capacity_kg: float | None) -> str | None:
    if capacity_kg is None:
        return None
    return "heavy" if capacity_kg >= 20000 else "medium" if capacity_kg >= 12000 else "light"


def model_dir() -> Path | None:
    raw = settings.eta_model_dir
    if raw is not None and raw.strip() == "":
        return None  # đặt rỗng = tắt
    return Path(raw) if raw else DEFAULT_DIR


def reset() -> None:
    """Chỉ để test: bắt buộc nạp lại."""
    global _state
    with _lock:
        _state = None


def _gate(card: dict) -> tuple[bool, str]:
    g = card.get("promotion_gate") or {}
    m = card.get("metrics_test") or {}
    try:
        imp, cov = float(m["improvement_vs_strongest_pct"]), float(m["p90_coverage"])
        need, (lo, hi) = float(g["min_mae_improvement_pct"]), g["p90_coverage_range"]
    except (KeyError, TypeError, ValueError):
        return False, "card_metrics_invalid"
    if imp < need:
        return False, "improvement_below_threshold"
    if not lo <= cov <= hi:
        return False, "p90_coverage_out_of_range"
    return (True, "ok") if g.get("passed") is True else (False, "gate_not_passed")


def _load() -> dict:
    d = model_dir()
    st: dict[str, Any] = {"present": False, "ok": False, "reason": "no_model", "card": None, "session": None, "gate_ok": False, "gate_reason": "no_model"}
    if d is None:
        return st
    card_p, onnx_p = d / "eta_model_card.json", d / "eta_model.onnx"
    if not card_p.exists() and not onnx_p.exists():
        return st
    st["present"], st["reason"] = True, "card_invalid"
    try:
        card = json.loads(card_p.read_text(encoding="utf-8"))
        assert isinstance(card, dict) and card.get("model_version")
    except Exception:  # noqa: BLE001
        return st
    st["card"] = card
    st["gate_ok"], st["gate_reason"] = _gate(card)
    if not onnx_p.exists():
        st["reason"] = "model_file_missing"
        return st
    if hashlib.sha256(onnx_p.read_bytes()).hexdigest() != card.get("sha256"):
        st["reason"] = "sha_mismatch"
        return st
    if card.get("feature_order") != EXPECTED_ORDER:
        st["reason"] = "feature_order_mismatch"
        return st
    try:
        import onnxruntime as ort
    except ImportError:
        st["reason"] = "runtime_missing"
        return st
    try:
        sess = ort.InferenceSession(str(onnx_p), providers=["CPUExecutionProvider"])
        import numpy as np
        out = sess.run(["eta"], {"features": np.array([[26.0, 8, 2, 0, 11, 0.0, 5.0, 1, 0, 0, 1, 0]], dtype="float32")})[0]
        assert out.shape == (1, 2) and out[0, 1] >= out[0, 0]  # hợp đồng đầu ra: [N,2], P90 ≥ P50
    except Exception:  # noqa: BLE001
        st["reason"] = "model_load_error"
        return st
    st["session"], st["ok"], st["reason"] = sess, True, "ok"
    return st


def state() -> dict:
    global _state
    with _lock:
        if _state is None:
            _state = _load()
        return _state


def available() -> bool:
    """Có thư mục model hợp lệ về hình thức (dù hỏng) → ONNX là nguồn ML chính thức; hỏng thì hạ về luật chứ KHÔNG lặng lẽ dùng mô hình mô phỏng cũ."""
    return state()["present"]


def promoted() -> tuple[bool, bool]:
    """(được dùng, bật thủ công dù cổng không đạt)."""
    st = state()
    if not st["ok"]:
        return False, False
    if st["gate_ok"]:
        return True, False
    return (True, True) if settings.eta_model_force else (False, False)


def model_info() -> dict:
    st = state()
    card = st["card"] or {}
    use, forced = promoted()
    m, base = card.get("metrics_test") or {}, (card.get("baselines_test") or {})
    name = m.get("strongest_baseline")
    b = base.get(name) or {}
    reason = ("gate_forced" if forced else "ok") if use else (st["reason"] if not st["ok"] else st["gate_reason"])
    return {
        "label": card.get("model_version", LABEL_FALLBACK), "source": "onnx", "is_simulated_history": True, "trained": st["ok"],
        "status": "forced" if forced else "promoted" if use else "rule_fallback", "reason": reason, "forced": forced,
        "sha256": card.get("sha256"), "baseline": name,
        "metrics": None if not m else {
            "n_train": None, "n_test": None, "split": "time-ordered (xem model card)", "mae_rule": b.get("mae_p50"), "mae_ml": m.get("mae_p50"),
            "improvement_pct": m.get("improvement_vs_strongest_pct"), "within15_rule": b.get("within15"), "within15_ml": m.get("within15"),
            "p90_coverage_rule": b.get("p90_coverage"), "p90_coverage_ml": m.get("p90_coverage"),
            "min_improvement_pct": (card.get("promotion_gate") or {}).get("min_mae_improvement_pct"),
            "coverage_target": (card.get("promotion_gate") or {}).get("p90_coverage_range"), "drift": None},
        "note": "Huấn luyện ngoài (Kaggle) trên dữ liệu MÔ PHỎNG — chỉ chứng minh quy trình, chưa chứng minh độ chính xác thật." +
                (" ⚠ Cổng promote KHÔNG đạt; đang bật thủ công (PIVOT_ETA_MODEL_FORCE) chỉ để thử." if forced else ""),
    }


def predict(depart_at: datetime, km: float, ctx: dict | None = None) -> dict | None:
    """(P50, P90) phút trung chuyển, hoặc None → dùng ETA luật. `ctx`: route_id, vehicle_class, rain_mm_h, wind_kmh.
    Khoá VẮNG mặt → dùng mặc định và ghi vào `assumed`; khoá có giá trị None → không biết → None (không đoán cho chuyến thật)."""
    try:
        use, forced = promoted()
        if not use:
            return None
        st, ctx = state(), ctx or {}
        assumed: list[str] = []
        vals = {}
        for k, dflt in DEFAULT_CTX.items():
            if k in ctx:
                if ctx[k] is None:
                    return None
                vals[k] = ctx[k]
            else:
                vals[k] = dflt
                assumed.append(k)
        if vals["route_id"] not in ROUTES or vals["vehicle_class"] not in VEHICLES:
            return None
        local = depart_at.astimezone(TZ)
        row = {"distance_km": float(km), "hour": local.hour, "weekday": local.weekday(), "month": local.month,
               "rain_mm_h": float(vals["rain_mm_h"]), "wind_kmh": float(vals["wind_kmh"])}
        rng = st["card"].get("valid_ranges") or {}
        for k, v in row.items():
            if k in rng and not (rng[k][0] <= v <= rng[k][1]):
                return None  # ngoài phạm vi đã huấn luyện → không ngoại suy
        import numpy as np
        x = np.array([[row["distance_km"], row["hour"], row["weekday"], int(row["weekday"] >= 5), row["month"], row["rain_mm_h"], row["wind_kmh"],
                       int(vals["route_id"] == ROUTES[0]), int(vals["route_id"] == ROUTES[1]),
                       int(vals["vehicle_class"] == "heavy"), int(vals["vehicle_class"] == "medium"), int(vals["vehicle_class"] == "light")]], dtype="float32")
        p50, p90 = (float(v) for v in st["session"].run(["eta"], {"features": x})[0][0])
        if not (p50 == p50 and p90 == p90) or p50 <= 0:
            return None
        p90 = max(p90, p50)
        conf = "low (simulated history)"
        if assumed:
            conf += f"; assumed {', '.join(assumed)}"
        if forced:
            conf += "; promotion gate NOT passed (manual override)"
        return {"p50_minutes": round(p50), "p90_minutes": round(p90), "method": "ml-onnx", "label": st["card"].get("model_version", LABEL_FALLBACK),
                "confidence": conf, "assumed": assumed, "forced": forced}
    except Exception:  # noqa: BLE001 — mọi lỗi lúc chạy → ETA luật
        return None
