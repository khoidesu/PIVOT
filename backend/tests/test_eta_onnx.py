"""Model ETA ONNX (huấn luyện ngoài trên dữ liệu MÔ PHỎNG): nạp + kiểm tra mã băm/hợp đồng, cổng promote, hạ về luật, ngữ cảnh chuyến thật.
`backend/model/` = model KHÔNG drift (qua cổng); `backend/model/archive_drift/` = model CÓ drift của Kaggle (cổng KHÔNG đạt) — dùng cho ca "cổng không đạt"."""
import csv
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from app import models as m
from app.config import settings
from app.db import SessionLocal
from app.eta import ml, onnx_model
from tests.conftest import auth
from tests.helpers import confirm_all, match

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "backend" / "model"
DRIFT_DIR = MODEL_DIR / "archive_drift"
CSV = ROOT / "data" / "eta_nodrift" / "eta_trips.csv"  # dữ liệu mà model chính được huấn luyện
pytestmark = pytest.mark.skipif(not ((MODEL_DIR / "eta_model.onnx").exists() and (DRIFT_DIR / "eta_model.onnx").exists()), reason="chưa có model trong backend/model")
TZ = timezone(timedelta(hours=7))


def at(h, wd_offset=0):  # thứ Tư 2026-11-11 + offset ngày, giờ địa phương
    return datetime(2026, 11, 11 + wd_offset, h, 0, tzinfo=TZ)


def use(monkeypatch, path, force=False):
    monkeypatch.setattr(settings, "eta_model_dir", str(path))
    monkeypatch.setattr(settings, "eta_model_force", force)
    onnx_model.reset()


@pytest.fixture()
def real(monkeypatch):
    """Model chính (không drift): qua cổng promote."""
    use(monkeypatch, MODEL_DIR)
    yield
    monkeypatch.undo()
    onnx_model.reset()


@pytest.fixture()
def drifted(monkeypatch):
    """Model có drift (cổng KHÔNG đạt), không ép."""
    use(monkeypatch, DRIFT_DIR)
    yield
    monkeypatch.undo()
    onnx_model.reset()


@pytest.fixture()
def drifted_forced(monkeypatch):
    use(monkeypatch, DRIFT_DIR, force=True)
    yield
    monkeypatch.undo()
    onnx_model.reset()


def tampered(tmp_path, monkeypatch, edit):
    d = tmp_path / "model"
    shutil.copytree(MODEL_DIR, d, ignore=shutil.ignore_patterns("*.ipynb"))
    edit(d)
    monkeypatch.setattr(settings, "eta_model_dir", str(d))
    onnx_model.reset()
    return d


# ---------------------------------------------------------------- nạp + cổng promote
def test_model_loads_and_the_card_hash_is_verified(real):
    st = onnx_model.state()
    card = json.loads((MODEL_DIR / "eta_model_card.json").read_text(encoding="utf-8"))
    assert st["present"] and st["ok"] and st["reason"] == "ok" and onnx_model.available()
    assert onnx_model.model_info()["sha256"] == card["sha256"] and onnx_model.model_info()["source"] == "onnx"
    info = ml.model_info()
    assert info["status"] == "promoted" and info["reason"] == "ok" and info["forced"] is False and card["promotion_gate"]["passed"] is True
    assert info["metrics"]["p90_coverage_ml"] >= info["metrics"]["coverage_target"][0] and info["metrics"]["improvement_pct"] >= info["metrics"]["min_improvement_pct"]


def test_gate_not_passed_means_rule_fallback_and_no_prediction(drifted):
    info = ml.model_info()
    assert info["source"] == "onnx" and info["status"] == "rule_fallback" and info["reason"] == "p90_coverage_out_of_range" and info["forced"] is False
    assert info["is_simulated_history"] is True and "MÔ PHỎNG" in info["note"]
    assert ml.predict(at(10), 26.0) is None and onnx_model.predict(at(10), 26.0) is None
    assert info["metrics"]["p90_coverage_ml"] < info["metrics"]["coverage_target"][0] and info["metrics"]["improvement_pct"] > info["metrics"]["min_improvement_pct"]


def test_force_override_predicts_but_is_always_labelled_manual(drifted_forced):
    info = ml.model_info()
    assert info["status"] == "forced" and info["forced"] is True and "bật thủ công" in info["note"]
    p = ml.predict(at(10), 26.0)
    assert p["method"] == "ml-onnx" and p["label"] == "eta-onnx-sim-v1" and 0 < p["p50_minutes"] <= p["p90_minutes"]
    assert "NOT passed" in p["confidence"] and p["forced"] is True
    assert set(p["assumed"]) == {"route_id", "vehicle_class", "rain_mm_h", "wind_kmh"}     # what-if: mặc định được ghi rõ


def test_gate_is_recomputed_from_the_card_metrics_not_just_the_flag(tmp_path, monkeypatch, real):
    def card_edit(**changes):
        def edit(d):
            c = json.loads((d / "eta_model_card.json").read_text(encoding="utf-8"))
            for k, v in changes.items():
                sect, key = k.split(".")
                c[sect][key] = v
            (d / "eta_model_card.json").write_text(json.dumps(c), encoding="utf-8")
        return edit
    tampered(tmp_path / "a", monkeypatch, card_edit(**{"metrics_test.p90_coverage": 0.70}))             # cờ passed=true nhưng số đo ngoài khoảng
    assert ml.model_info()["reason"] == "p90_coverage_out_of_range" and ml.predict(at(10), 26.0) is None
    tampered(tmp_path / "b", monkeypatch, card_edit(**{"metrics_test.improvement_vs_strongest_pct": 5.0}))
    assert ml.model_info()["reason"] == "improvement_below_threshold" and ml.predict(at(10), 26.0) is None
    tampered(tmp_path / "c", monkeypatch, card_edit(**{"promotion_gate.passed": False}))                # số đo tốt nhưng cờ nói không đạt → tôn trọng cờ
    assert ml.model_info()["reason"] == "gate_not_passed" and ml.predict(at(10), 26.0) is None


# ---------------------------------------------------------------- hạ về luật khi model hỏng / lạ
@pytest.mark.parametrize("name,edit,reason", [
    ("sha", lambda d: (d / "eta_model.onnx").write_bytes((d / "eta_model.onnx").read_bytes() + b"x"), "sha_mismatch"),
    ("order", lambda d: (d / "eta_model_card.json").write_text(json.dumps({**json.loads((d / "eta_model_card.json").read_text(encoding="utf-8")),
                                                                         "feature_order": ["a", "b"]}), encoding="utf-8"), "feature_order_mismatch"),
    ("badcard", lambda d: (d / "eta_model_card.json").write_text("{không phải json", encoding="utf-8"), "card_invalid"),
    ("nofile", lambda d: (d / "eta_model.onnx").unlink(), "model_file_missing"),
])
def test_broken_model_never_predicts_even_when_forced(tmp_path, monkeypatch, real, name, edit, reason):
    monkeypatch.setattr(settings, "eta_model_force", True)
    tampered(tmp_path, monkeypatch, edit)
    info = ml.model_info()
    assert onnx_model.available() and info["status"] == "rule_fallback" and info["reason"] == reason and info["source"] == "onnx"
    assert ml.predict(at(10), 26.0) is None                                                # hỏng → luật, KHÔNG lặng lẽ dùng mô hình mô phỏng cũ


def test_missing_or_disabled_model_dir_falls_back_to_the_old_simulated_model(tmp_path, monkeypatch, real):
    for d in (str(tmp_path / "empty"), ""):
        monkeypatch.setattr(settings, "eta_model_dir", d)
        onnx_model.reset()
        assert not onnx_model.available() and ml.model_info()["source"] == "sim"


# ---------------------------------------------------------------- dự báo có hợp lý
def test_predictions_are_plausible_and_respond_to_inputs(real):
    p = lambda **k: ml.predict(k.pop("t", at(10)), k.pop("km", 26.0), k or None)         # noqa: E731
    base = p()
    assert 55 <= base["p50_minutes"] <= 140 and base["p50_minutes"] <= base["p90_minutes"]
    assert p(km=35.0)["p50_minutes"] > base["p50_minutes"] > p(km=15.0)["p50_minutes"]    # càng xa càng lâu
    assert p(t=at(17))["p50_minutes"] > p(t=at(2))["p50_minutes"]                        # cao điểm chiều chậm hơn ban đêm
    assert p(rain_mm_h=20.0)["p50_minutes"] >= p(rain_mm_h=0.0)["p50_minutes"]
    assert p(vehicle_class="heavy")["p50_minutes"] >= p(vehicle_class="light")["p50_minutes"]


def test_inputs_outside_the_training_range_or_unknown_return_none(real):
    assert ml.predict(at(10), 5.0) is None and ml.predict(at(10), 60.0) is None          # ngoài 8–40 km: không ngoại suy
    assert ml.predict(at(10), 26.0, {"rain_mm_h": 99}) is None
    assert ml.predict(at(10), 26.0, {"route_id": None}) is None                           # chuyến thật không rõ tuyến → không đoán
    assert ml.predict(at(10), 26.0, {"vehicle_class": "tank"}) is None
    assert onnx_model.route_id_for("KCN Sóng Thần (mô phỏng)") == "KCN_A_ICD" and onnx_model.route_id_for("KCN VSIP I (mô phỏng)") == "KCN_B_ICD"
    assert onnx_model.route_id_for("Depot Thủ Đức") is None and onnx_model.vehicle_class_for(24000) == "heavy" and onnx_model.vehicle_class_for(18000) == "medium"
    assert onnx_model.vehicle_class_for(8000) == "light" and onnx_model.vehicle_class_for(None) is None


@pytest.mark.skipif(not CSV.exists(), reason="chưa có data/eta_nodrift/eta_trips.csv")
def test_backend_reproduces_the_metrics_in_the_model_card_on_the_test_split(real):
    """Kiểm tra chéo ánh xạ đặc trưng backend ↔ notebook: chạy predict() trên tập test của CSV phải ra MAE/độ phủ như model card."""
    card = json.loads((MODEL_DIR / "eta_model_card.json").read_text(encoding="utf-8"))["metrics_test"]
    err, cover, n = [], [], 0
    with CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["split"] != "test":
                continue
            p = ml.predict(datetime.fromisoformat(r["depart_at"]), float(r["distance_km"]),
                           {"route_id": r["route_id"], "vehicle_class": r["vehicle_class"], "rain_mm_h": float(r["rain_mm_h"]), "wind_kmh": float(r["wind_kmh"])})
            y = float(r["actual_transit_min"])
            err.append(abs(p["p50_minutes"] - y)); cover.append(y <= p["p90_minutes"]); n += 1
    assert n > 3000
    assert np.mean(err) == pytest.approx(card["mae_p50"], abs=0.4)                      # sai khác chỉ do làm tròn phút
    assert np.mean(cover) == pytest.approx(card["p90_coverage"], abs=0.02)


# ---------------------------------------------------------------- endpoint + chuyến thật
def test_endpoints_expose_source_gate_and_accept_optional_context(client, real):
    d = client.get("/v1/eta/model", headers=auth("shipper_a")).json()
    assert d["source"] == "onnx" and d["status"] == "promoted" and d["label"] == "eta-onnx-sim-v1" and d["metrics"]["mae_ml"] < d["metrics"]["mae_rule"]
    body = {"depart_at": at(10).isoformat(), "km": 26, "route_id": "KCN_B_ICD", "vehicle_class": "heavy", "rain_mm_h": 5, "wind_kmh": 10}
    w = client.post("/v1/eta/predict", json=body, headers=auth("carrier_b")).json()
    assert w["used"] == "ml" and w["ml"]["assumed"] == [] and w["rule"]["p50"] <= w["rule"]["p90"] and w["status"] == "promoted"
    assert client.post("/v1/eta/predict", json={**body, "route_id": "X"}, headers=auth("carrier_b")).status_code == 422
    assert client.post("/v1/eta/predict", json={**body, "rain_mm_h": 99}, headers=auth("carrier_b")).status_code == 422


def test_gate_not_passed_the_predict_endpoint_uses_rules(client, drifted):
    w = client.post("/v1/eta/predict", json={"depart_at": at(10).isoformat()}, headers=auth("carrier_b")).json()
    assert w["used"] == "rule" and w["ml"] is None and w["status"] == "rule_fallback"


def test_real_trip_gets_its_own_route_vehicle_and_unknown_route_falls_back(client, real):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    t = client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()
    ml_eta = t["eta_ml"]
    assert ml_eta and ml_eta["method"] == "ml-onnx" and "route_id" not in ml_eta["assumed"] and "vehicle_class" not in ml_eta["assumed"]
    assert set(ml_eta["assumed"]) == {"rain_mm_h", "wind_kmh"}                          # tín hiệu thời tiết tắt trong test → giả định khô, ghi rõ
    with SessionLocal() as s:                                                           # điểm lấy hàng không nhận ra → không đoán
        ship = s.get(m.Shipment, __import__("uuid").UUID(prop["shipment"]["id"]))
        ship.origin_location_id = s.query(m.Location).filter(m.Location.kind == "depot").one().id
        s.commit()
    assert client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()["eta_ml"] is None


def test_gate_not_passed_trip_shows_no_ml_eta(client, drifted):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    assert client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()["eta_ml"] is None


def test_training_inside_the_app_is_refused_while_the_onnx_model_is_the_source(client, real):
    r = client.post("/v1/eta/train", json={"drift": 0.15}, headers=auth("dispatch"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ONNX_MODEL_IN_USE"
    assert client.get("/v1/eta/model", headers=auth("shipper_a")).json()["status"] == "promoted"     # model đang dùng không bị đụng


def test_demo_scenario_eta_model_passes_with_the_onnx_model_too(client, real):
    r = client.post("/v1/demo/scenarios/eta_model/run", headers=auth("dispatch"))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["passed"], [s for s in out["steps"] if not s["ok"]]
    assert any("409" in s["label"] for s in out["steps"])                                            # đã đi nhánh ONNX, không phải nhánh mô phỏng
