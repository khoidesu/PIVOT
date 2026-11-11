"""ETA: baseline luật P50/P90 theo khung giờ, ETA trực tiếp, DELAY_RISK, ML mô phỏng (chia theo thời gian, cổng promote, tự hạ về luật)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import models as m
from app.db import SessionLocal
from app.eta import baseline, live, ml
from app.seed import ASSUMPTIONS_V1
from app.sim import gps
from tests.conftest import auth
from tests.helpers import confirm_all, match, run_worker

PARAMS = ASSUMPTIONS_V1
UTC = timezone.utc


def at_local_hour(h):  # giờ Việt Nam (UTC+7)
    return datetime(2026, 11, 11, h, 0, tzinfo=timezone(timedelta(hours=7))).astimezone(UTC)


@pytest.fixture(autouse=True)
def _restore_model():
    yield
    ml.train()  # các test đổi trạng thái mô hình toàn cục → luôn trả về cấu hình mặc định


# ---------------------------------------------------------------- baseline luật
def test_bands_follow_local_hours_and_widen_only_p90():
    assert [baseline.band_for(at_local_hour(h), PARAMS) for h in (3, 8, 12, 17, 23)] == ["night", "peak_am", "normal", "peak_pm", "night"]
    p50 = at_local_hour(10)
    spread = {b: baseline.p90_extra_minutes(115, b, PARAMS) for b in ("night", "normal", "peak_am", "peak_pm")}
    assert spread["night"] < spread["normal"] < spread["peak_am"] < spread["peak_pm"]
    out = {h: baseline.interval(p50, 115, at_local_hour(h), PARAMS) for h in (3, 12, 17)}
    assert len({o["p50"] for o in out.values()}) == 1                          # P50 không đổi theo khung giờ (hard gate ổn định)
    assert all(datetime.fromisoformat(o["p90"]) > datetime.fromisoformat(o["p50"]) for o in out.values())


def test_proposal_eta_carries_p50_p90_and_labels_itself_rule_based(client):
    for p in match(client, "shipper_a", "LOT-A-001")["proposals"]:
        e = p["eta"]
        assert e["method"] == "rule-based" and "low" in e["confidence"] and e["model_version"] == "eta-rule-v1"
        assert datetime.fromisoformat(e["pickup"]) <= datetime.fromisoformat(e["pickup_p90"])
        assert datetime.fromisoformat(e["icd"]) <= datetime.fromisoformat(e["icd_p90"])
        assert isinstance(e["cutoff_risk_p90"], bool)
        assert p["assumption_version"] == "assume-v2"


def test_cutoff_risk_flag_is_soft_and_uses_p90():
    pickup = at_local_hour(12)
    loose = baseline.build(pickup, at_local_hour(11), PARAMS, cutoff_at=pickup + timedelta(hours=8))
    tight = baseline.build(pickup, at_local_hour(11), PARAMS, cutoff_at=pickup + timedelta(minutes=125))   # P50 vừa kịp, P90 thì không
    assert loose["cutoff_risk_p90"] is False and tight["cutoff_risk_p90"] is True


# ---------------------------------------------------------------- ETA trực tiếp + DELAY_RISK
def _running(client):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    assert client.post(f"/v1/sim/{prop['id']}/start", headers=auth("carrier_b")).status_code == 200
    run_worker(client)
    with SessionLocal() as s:
        t0 = s.get(m.SimTrip, uuid.UUID(prop["id"])).updated_at
    return prop, t0


def _tick(t0, seconds):
    with SessionLocal() as s:
        gps.tick(s, t0 + timedelta(seconds=seconds)); s.commit()


def test_live_eta_uses_observed_speed_and_never_invents_an_eta_for_a_stalled_truck(client):
    prop, t0 = _running(client)
    for i in (1, 2, 3):
        _tick(t0, i * 5); run_worker(client)
    e = client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()["eta"]
    assert e["method"] == "rule-based/live" and e["stalled"] is False
    assert datetime.fromisoformat(e["p50"]) <= datetime.fromisoformat(e["p90"]) and e["speed_kmh"] > 0
    client.post(f"/v1/sim/{prop['id']}/mode", json={"mode": "breakdown"}, headers=auth("carrier_b"))
    for i in (4, 5, 6, 7, 8, 9):
        _tick(t0, i * 5); run_worker(client)
    e2 = client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()["eta"]
    assert e2["stalled"] is True and e2["p50"] is None and e2["cutoff_risk"] is True      # xe đứng yên: không bịa ETA
    risks = [x for x in client.get("/v1/exceptions", headers=auth("shipper_a")).json() if x["exc_type"] == "DELAY_RISK"]
    assert len(risks) == 1 and risks[0]["severity"] == "critical"                          # nguy cơ lỡ cut-off → critical, một lần


def test_planned_p90_beyond_cutoff_opens_one_delay_risk_before_any_delay(client):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    with SessionLocal() as s:  # giả lập: P90 kế hoạch vượt cut-off (cờ mềm trong snapshot ETA)
        p = s.get(m.Proposal, uuid.UUID(prop["id"]))
        p.input_snapshot = {**p.input_snapshot, "eta": {**p.input_snapshot["eta"], "cutoff_risk_p90": True}}
        s.commit()
    run_worker(client); run_worker(client)
    rows = [x for x in client.get("/v1/exceptions", headers=auth("node_c")).json() if x["exc_type"] == "DELAY_RISK"]
    assert len(rows) == 1 and rows[0]["detail"]["basis"] == "plan_p90"


# ---------------------------------------------------------------- ML mô phỏng
def test_training_is_deterministic_and_split_is_chronological():
    a = ml.train()["metrics"]; b = ml.train()["metrics"]
    assert a == b
    assert a["n_train"] + a["n_calibration"] + a["n_test"] == ml.N_TRIPS and a["n_train"] < a["n_train"] + a["n_calibration"] < ml.N_TRIPS
    _, y, idx = ml.simulate_history(90.0, drift=0.0)
    assert list(idx) == sorted(idx) and len(y) == ml.N_TRIPS


def test_no_future_leakage_a_drift_that_appears_only_in_test_is_not_hidden_by_the_model():
    base = ml.train(drift=0.0)["metrics"]["p90_coverage_ml"]
    drifted = ml.train(drift=0.15)["metrics"]["p90_coverage_ml"]
    assert drifted < base - 0.15       # nếu test lọt vào huấn luyện/hiệu chỉnh thì độ phủ đã không tụt


def test_promotion_gate_and_automatic_fallback_to_rule():
    ok = ml.train()
    assert ok["status"] == "promoted" and ok["metrics"]["improvement_pct"] >= 15
    assert ml.COVERAGE_RANGE[0] <= ok["metrics"]["p90_coverage_ml"] <= ml.COVERAGE_RANGE[1]
    p = ml.predict(at_local_hour(8))
    assert p and p["p50_minutes"] <= p["p90_minutes"] and "simulated" in p["confidence"]
    bad = ml.train(drift=0.15)
    assert bad["status"] == "rule_fallback" and bad["reason"] == "p90_coverage_out_of_range" and ml.predict(at_local_hour(8)) is None
    worse = ml.train(drift=0.5)
    assert worse["status"] == "rule_fallback"


def test_model_error_at_prediction_time_falls_back_to_rule(monkeypatch):
    ml.train()
    monkeypatch.setitem(ml._state, "m50", None)  # mô hình hỏng
    assert ml.predict(at_local_hour(8)) is None


def test_eta_endpoints_label_simulation_and_restrict_training(client):
    d = client.get("/v1/eta/model", headers=auth("shipper_a")).json()
    assert d["is_simulated_history"] is True and d["status"] in ("promoted", "rule_fallback") and "MÔ PHỎNG" in d["note"]
    assert client.post("/v1/eta/train", json={}, headers=auth("shipper_a")).status_code == 403
    r = client.post("/v1/eta/train", json={"drift": 0.15}, headers=auth("dispatch"))
    assert r.status_code == 200 and r.json()["status"] == "rule_fallback"
    w = client.post("/v1/eta/predict", json={"depart_at": at_local_hour(8).isoformat()}, headers=auth("carrier_b")).json()
    assert w["used"] == "rule" and w["ml"] is None and w["rule"]["p50"] <= w["rule"]["p90"] and w["is_simulated"] is True
    assert client.post("/v1/eta/train", json={"drift": 2}, headers=auth("dispatch")).status_code == 422
    client.post("/v1/eta/train", json={"drift": 0}, headers=auth("dispatch"))
    w2 = client.post("/v1/eta/predict", json={"depart_at": at_local_hour(8).isoformat()}, headers=auth("carrier_b")).json()
    assert w2["used"] == "ml" and w2["ml"]["p50_minutes"] <= w2["ml"]["p90_minutes"]
