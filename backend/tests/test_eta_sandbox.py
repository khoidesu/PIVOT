"""ETA Sandbox (công cụ nội bộ): quét độ trôi, lưới kịch bản, sức khoẻ tín hiệu, endpoint dispatcher, CLI. Không gọi mạng thật."""
from datetime import datetime, timedelta, timezone

import pytest

from app import eta_sandbox_cli
from app.config import settings
from app.eta import baseline, ml, sandbox, signals
from app.seed import ASSUMPTIONS_V1
from tests.conftest import auth
from tests.test_eta_signals import fake_mapbox, osrm_response

WEATHER = {"current": {"time": "2026-11-11T10:00", "precipitation": 0.0, "weather_code": 1, "wind_speed_10m": 6.0}}


@pytest.fixture(autouse=True)
def _restore_model_and_cache():
    signals.clear_cache()
    yield
    ml.train()  # mô hình dùng chung → luôn trả về cấu hình mặc định sau mỗi test
    signals.clear_cache()


def network(monkeypatch, *, osrm=True, weather=True, mapbox=True):
    """Mạng giả: định tuyến theo URL; nguồn bị tắt thì ném lỗi như dịch vụ chết."""
    mb = fake_mapbox()

    def get(url, params=None):
        if "open-meteo" in url:
            if not weather:
                raise TimeoutError("weather down")
            return WEATHER
        if "mapbox" in url:
            if not mapbox:
                raise TimeoutError("mapbox down")
            return mb(url, params)
        if not osrm:
            raise TimeoutError("osrm down")
        return osrm_response()
    monkeypatch.setattr(signals, "_get_json", get)


# ---------------------------------------------------------------- 1. quét độ trôi
def test_drift_sweep_promotes_without_drift_and_falls_back_with_high_drift():
    rows = sandbox.sweep_drift()
    assert [r["drift"] for r in rows] == list(sandbox.DEFAULT_DRIFTS)
    assert rows[0]["promoted"] is True and rows[0]["status"] == "promoted" and rows[0]["reason"] == "ok"
    assert rows[-1]["drift"] == 0.3 and rows[-1]["promoted"] is False and rows[-1]["status"] == "rule_fallback"
    assert {"drift", "promoted", "mae_rule", "mae_ml", "improvement_pct", "p90_coverage_ml", "status", "reason"} <= set(rows[0])
    assert rows[0]["improvement_pct"] >= ml.MIN_IMPROVEMENT * 100                       # đúng cổng promote của ml.train, không tính lại
    assert rows[0]["mae_ml"] < rows[0]["mae_rule"]


def test_drift_sweep_accepts_a_custom_list_and_matches_ml_train():
    rows = sandbox.sweep_drift([0.0, 0.15])
    direct = ml.train(drift=0.15)
    assert [r["drift"] for r in rows] == [0.0, 0.15]
    assert rows[1]["mae_ml"] == direct["metrics"]["mae_ml"] and rows[1]["status"] == direct["status"]


@pytest.mark.parametrize("prior_drift", [0.0, 0.15])
def test_drift_sweep_restores_the_model_state_it_found(prior_drift):
    ml.train(drift=prior_drift)
    before = (ml.model_info(), ml.predict(datetime(2026, 11, 11, 1, 0, tzinfo=timezone.utc)))
    sandbox.sweep_drift()
    after = (ml.model_info(), ml.predict(datetime(2026, 11, 11, 1, 0, tzinfo=timezone.utc)))
    assert after == before                                                              # sandbox không đổi hành vi production


def test_drift_sweep_restores_state_even_if_training_fails(monkeypatch):
    ml.train(drift=0.0)
    before = ml.model_info()
    monkeypatch.setattr(ml, "train", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        sandbox.sweep_drift([0.0])
    monkeypatch.undo()
    assert ml.model_info() == before


# ---------------------------------------------------------------- 2. lưới kịch bản
def test_scenario_matrix_covers_every_band_and_matches_the_predict_logic():
    rows = sandbox.scenario_matrix()
    assert [r["band"] for r in rows] == ["peak_am", "peak_pm", "night", "normal"]
    tz = timezone(timedelta(hours=ASSUMPTIONS_V1["eta"]["tz_offset_hours"]))
    for r in rows:
        depart = datetime(2026, 11, 11, r["depart_hour"], tzinfo=tz)
        assert baseline.band_for(depart, ASSUMPTIONS_V1) == r["band"]                  # giờ chọn đúng khung (hỏi chính baseline)
        assert r["rule_p50"] == ASSUMPTIONS_V1["transit_minutes"] and r["rule_p90"] > r["rule_p50"]   # P50 luật không đổi theo khung giờ
    p90 = {r["band"]: r["rule_p90"] for r in rows}
    assert p90["night"] < p90["normal"] < p90["peak_am"] < p90["peak_pm"]
    assert all(r["used"] == "ml" and r["ml_p50"] <= r["ml_p90"] for r in rows)         # mặc định ML được promote


def test_scenario_matrix_uses_rules_when_the_model_is_not_promoted():
    ml.train(drift=0.3)
    rows = sandbox.scenario_matrix()
    assert all(r["used"] == "rule" and r["ml_p50"] is None and r["ml_p90"] is None and r["model_status"] == "rule_fallback" for r in rows)


def test_scenario_rows_equal_the_predict_endpoint(client):
    for r in sandbox.scenario_matrix():
        depart = datetime(2026, 11, 11, r["depart_hour"], tzinfo=timezone(timedelta(hours=7)))
        w = client.post("/v1/eta/predict", json={"depart_at": depart.isoformat()}, headers=auth("carrier_b")).json()
        assert w["rule"]["minutes_p50"] == r["rule_p50"] and w["used"] == r["used"] and w["ml"]["p50_minutes"] == r["ml_p50"]


# ---------------------------------------------------------------- 3. sức khoẻ tín hiệu
def test_signals_health_disabled_reports_disabled_and_never_touches_the_network(monkeypatch):
    monkeypatch.setattr(settings, "signals_enabled", False)
    monkeypatch.setattr(signals, "_get_json", lambda *a, **k: pytest.fail("must not call the network when signals are disabled"))
    h = sandbox.signals_health_check()
    assert (h["enabled"], h["osrm"]["status"], h["weather"]["status"], h["mapbox"]["status"]) == (False, "disabled", "disabled", "disabled")


def test_signals_health_ok_for_osrm_and_weather_and_mapbox_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "signals_enabled", True)
    monkeypatch.setattr(settings, "mapbox_token", None)
    network(monkeypatch)
    h = sandbox.signals_health_check()
    assert h["osrm"]["status"] == "ok" and h["osrm"]["distance_km"] == 24.0 and h["weather"]["status"] == "ok"
    assert h["mapbox_configured"] is False and h["mapbox"]["status"] == "not_configured"
    assert h["health"]["osrm"]["ok"] is True and h["sample_points"] == list(sandbox.DEFAULT_POINTS)


def test_signals_health_with_mapbox_configured_never_leaks_the_token(monkeypatch):
    monkeypatch.setattr(settings, "signals_enabled", True)
    monkeypatch.setattr(settings, "mapbox_token", "pk.SECRET-TEST-TOKEN")
    network(monkeypatch)
    h = sandbox.signals_health_check()
    assert h["mapbox_configured"] is True and h["mapbox"]["status"] == "ok" and h["mapbox"]["live_min"] == 30.0
    assert "SECRET" not in repr(h)


def test_signals_health_catches_each_failure_without_crashing(monkeypatch):
    monkeypatch.setattr(settings, "signals_enabled", True)
    monkeypatch.setattr(settings, "mapbox_token", "pk.SECRET-TEST-TOKEN")
    network(monkeypatch, osrm=False, weather=False, mapbox=False)
    h = sandbox.signals_health_check()
    assert (h["osrm"]["status"], h["weather"]["status"], h["mapbox"]["status"]) == ("error", "error", "error")
    assert h["health"]["osrm"]["ok"] is False and "SECRET" not in repr(h)
    monkeypatch.setattr(signals, "fetch_weather", lambda *a: (_ for _ in ()).throw(RuntimeError("bug")))   # ngay cả lỗi bất ngờ cũng được bắt gọn
    assert sandbox.signals_health_check()["weather"]["status"] == "error"


def test_signals_health_fresh_bypasses_the_failure_cache(monkeypatch):
    monkeypatch.setattr(settings, "signals_enabled", True)
    monkeypatch.setattr(settings, "mapbox_token", None)
    network(monkeypatch, osrm=False)
    assert sandbox.signals_health_check()["osrm"]["status"] == "error"
    network(monkeypatch)                                                                # dịch vụ hồi phục
    assert sandbox.signals_health_check()["osrm"]["status"] == "error"                  # lỗi còn được nhớ 60 giây
    assert sandbox.signals_health_check(fresh=True)["osrm"]["status"] == "ok"


def test_signals_health_needs_three_points():
    with pytest.raises(ValueError):
        sandbox.signals_health_check([(10.9, 106.7)])


# ---------------------------------------------------------------- endpoint (chỉ điều phối viên)
@pytest.mark.parametrize("path", ["/v1/eta/sandbox/drift-sweep", "/v1/eta/sandbox/scenarios", "/v1/eta/sandbox/signals-health"])
def test_sandbox_endpoints_are_dispatcher_only(client, path):
    for who in ("shipper_a", "carrier_b", "node_c"):
        assert client.get(path, headers=auth(who)).status_code == 403
    assert client.get(path).status_code == 401


def test_sandbox_endpoints_work_and_leave_the_model_untouched(client, monkeypatch):
    monkeypatch.setattr(settings, "signals_enabled", False)
    before = client.get("/v1/eta/model", headers=auth("shipper_a")).json()
    sweep = client.get("/v1/eta/sandbox/drift-sweep", headers=auth("dispatch")).json()
    scen = client.get("/v1/eta/sandbox/scenarios", headers=auth("dispatch")).json()
    sig = client.get("/v1/eta/sandbox/signals-health", headers=auth("dispatch")).json()
    assert sweep[0]["promoted"] is True and sweep[-1]["promoted"] is False
    assert len(scen) == 4 and sig["osrm"]["status"] == "disabled"
    assert client.get("/v1/eta/model", headers=auth("shipper_a")).json() == before


def test_sandbox_endpoint_respects_the_admin_key(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_key", "k-test")
    assert client.get("/v1/eta/sandbox/scenarios", headers=auth("dispatch")).status_code == 403
    assert client.get("/v1/eta/sandbox/scenarios", headers={**auth("dispatch"), "X-Admin-Key": "k-test"}).status_code == 200


# ---------------------------------------------------------------- CLI
def test_cli_prints_the_three_tables_without_server_or_network(monkeypatch, capsys):
    monkeypatch.setattr(settings, "signals_enabled", False)
    monkeypatch.setattr(signals, "_get_json", lambda *a, **k: pytest.fail("no network"))
    assert eta_sandbox_cli.main([]) == 0
    out = capsys.readouterr().out
    assert "Quét độ trôi" in out and "hạ về luật từ drift" in out and "peak_am" in out and "disabled" in out
    assert eta_sandbox_cli.main(["--only", "scenarios"]) == 0 and "Quét độ trôi" not in capsys.readouterr().out
    assert eta_sandbox_cli.main(["--only", "nope"]) == 2
