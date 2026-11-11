"""ETA tầng 2: tín hiệu thật (OSRM + thời tiết) — kiểm thử bằng máy chủ giả (không gọi mạng thật), cache, lỗi → hạ về luật."""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.eta import signals
from app.seed import ASSUMPTIONS_V1

UTC = timezone.utc
START, PICKUP, DEST = (10.87, 106.77), (10.9, 106.74), (10.85, 106.8)


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "signals_enabled", True)
    signals.clear_cache()
    yield
    signals.clear_cache()


def osrm_response(n_points=50, pickup_at=20):
    """Phản hồi OSRM giả: đường thẳng nhiều điểm, đi qua điểm lấy hàng ở chỉ số pickup_at."""
    pts = []
    for i in range(n_points):
        t = i / (n_points - 1)
        pts.append((START[0] + (DEST[0] - START[0]) * t, START[1] + (DEST[1] - START[1]) * t))
    pts[pickup_at] = PICKUP
    return {"code": "Ok", "routes": [{"distance": 24000.0, "duration": 3000.0, "geometry": {"coordinates": [[lng, lat] for lat, lng in pts]},
                                      "legs": [{"duration": 1000.0}, {"duration": 2000.0}]}]}


def at_local_hour(h):
    return datetime(2026, 11, 11, h, 0, tzinfo=timezone(timedelta(hours=7))).astimezone(UTC)


# ------------------------------------------------------------------ tuyến đường bộ
def test_road_route_parses_osrm_and_finds_pickup_index(monkeypatch):
    monkeypatch.setattr(signals, "_get_json", lambda url, params=None: osrm_response())
    r = signals.fetch_road_route(START, PICKUP, DEST)
    assert r["source"] == "osrm" and r["distance_km"] == 24.0 and r["duration_min"] == 50.0 and r["leg_minutes"] == [16.7, 33.3]
    assert r["points"][r["pickup_index"]] == PICKUP
    assert r["points"][0][0] == pytest.approx(START[0]) and r["points"][-1][0] == pytest.approx(DEST[0])


def test_road_route_is_thinned_but_keeps_pickup_and_ends(monkeypatch):
    monkeypatch.setattr(signals, "_get_json", lambda url, params=None: osrm_response(n_points=3000, pickup_at=1234))
    r = signals.fetch_road_route(START, PICKUP, DEST)
    assert len(r["points"]) <= signals.PARAMS["max_points"] + 3
    assert r["points"][r["pickup_index"]] == PICKUP and r["points"][-1][0] == pytest.approx(DEST[0])


def test_road_route_is_cached_and_failure_is_negative_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(signals, "_get_json", lambda url, params=None: calls.append(url) or osrm_response())
    signals.fetch_road_route(START, PICKUP, DEST)
    signals.fetch_road_route(START, PICKUP, DEST)
    assert len(calls) == 1                                           # lần 2 lấy từ cache

    def boom(url, params=None):
        calls.append("boom")
        raise TimeoutError("down")
    signals.clear_cache()
    calls.clear()
    monkeypatch.setattr(signals, "_get_json", boom)
    assert signals.fetch_road_route(START, PICKUP, DEST) is None
    assert signals.fetch_road_route(START, PICKUP, DEST) is None
    assert calls == ["boom"]                                         # dịch vụ chết: không gọi dồn dập lại trong 60 giây
    assert signals.health()["osrm"]["ok"] is False


def test_bad_osrm_payloads_fall_back_to_none(monkeypatch):
    for bad in ({"code": "NoRoute", "routes": []}, {"code": "Ok", "routes": []}, {"code": "Ok", "routes": [{"geometry": {"coordinates": [[1, 2]]}, "legs": [],
                                                                                                           "distance": 1, "duration": 1}]}):
        signals.clear_cache()
        monkeypatch.setattr(signals, "_get_json", lambda url, params=None, b=bad: b)
        assert signals.fetch_road_route(START, PICKUP, DEST) is None


def test_disabled_makes_no_network_calls(monkeypatch):
    monkeypatch.setattr(settings, "signals_enabled", False)
    monkeypatch.setattr(signals, "_get_json", lambda *a, **k: pytest.fail("must not call network when disabled"))
    assert signals.fetch_road_route(START, PICKUP, DEST) is None and signals.fetch_weather(10.9, 106.7) is None


def test_vehicle_already_at_pickup_uses_two_waypoints(monkeypatch):
    seen = []
    monkeypatch.setattr(signals, "_get_json", lambda url, params=None: seen.append(url) or osrm_response(pickup_at=0))
    r = signals.fetch_road_route(PICKUP, PICKUP, DEST)
    assert seen[0].count(";") == 1 and r["pickup_index"] == 0


# ------------------------------------------------------------------ thời tiết
def wx(mm=0.0, code=0, wind=5.0):
    return {"precip_mm_h": mm, "weather_code": code, "wind_kmh": wind, "source": "open-meteo"}


def test_weather_factor_steps_with_rain_thunder_and_wind():
    f = signals.weather_factor
    assert f(None) == 1.0 and f(wx()) == 1.0                         # thiếu dữ liệu ≠ bịa phạt
    assert 1.0 < f(wx(1.0)) < f(wx(5.0)) < f(wx(20.0))
    assert f(wx(0.0, code=95)) >= 1.3                                # dông
    assert f(wx(0.0, wind=70)) > f(wx(0.0, wind=10))


def test_fetch_weather_parses_open_meteo_and_rounds_coords(monkeypatch):
    seen = []

    def fake(url, params=None):
        seen.append(params)
        return {"current": {"time": "2026-11-11T10:00", "precipitation": 3.2, "weather_code": 63, "wind_speed_10m": 12.0}}
    monkeypatch.setattr(signals, "_get_json", fake)
    a = signals.fetch_weather(10.8712, 106.7701)
    b = signals.fetch_weather(10.8699, 106.7688)                     # cùng ô 0,05° → dùng chung cache
    assert a == b and a["precip_mm_h"] == 3.2 and len(seen) == 1
    monkeypatch.setattr(signals, "_get_json", lambda *x, **k: {"current": {}})
    signals.clear_cache()
    assert signals.fetch_weather(10.9, 106.7) is None                # thiếu trường → None, không đoán


# ------------------------------------------------------------------ ước tính ETA
ROAD = {"source": "osrm", "distance_km": 24.0, "duration_min": 50.0}


def test_estimate_orders_by_band_and_weather_and_p90_above_p50():
    p = ASSUMPTIONS_V1
    night = signals.estimate(ROAD, wx(), 1.0, at_local_hour(3), p)
    peak = signals.estimate(ROAD, wx(), 1.0, at_local_hour(17), p)
    rainy = signals.estimate(ROAD, wx(12.0), 1.0, at_local_hour(12), p)
    dry = signals.estimate(ROAD, wx(), 1.0, at_local_hour(12), p)
    assert night["minutes_p50"] < dry["minutes_p50"] < peak["minutes_p50"] and dry["minutes_p50"] < rainy["minutes_p50"]
    for e in (night, peak, rainy, dry):
        assert e["status"] == "ok" and e["method"] == "rule-based+signals" and e["minutes_p90"] > e["minutes_p50"]
        assert datetime.fromisoformat(e["p90"]) > datetime.fromisoformat(e["p50"])
    assert dry["minutes_p50"] == pytest.approx(50 * 1.25 * 1.0, abs=0.1)         # 50' × xe tải × khung thường × trời khô


def test_estimate_scales_with_remaining_fraction():
    full = signals.estimate(ROAD, wx(), 1.0, at_local_hour(12), ASSUMPTIONS_V1)
    half = signals.estimate(ROAD, wx(), 0.5, at_local_hour(12), ASSUMPTIONS_V1)
    done = signals.estimate(ROAD, wx(), 0.0, at_local_hour(12), ASSUMPTIONS_V1)
    assert half["minutes_p50"] == pytest.approx(full["minutes_p50"] / 2, abs=0.1) and done["minutes_p50"] == 0.0


def test_estimate_degrades_honestly_when_sources_missing():
    now = at_local_hour(12)
    none = signals.estimate(None, None, 1.0, now, ASSUMPTIONS_V1)
    assert none["status"] == "fallback" and none["p50"] is None and "low" in none["confidence"] and none["sources"] == {"route": None, "weather": None}
    partial = signals.estimate(ROAD, None, 1.0, now, ASSUMPTIONS_V1)             # có đường, thiếu thời tiết
    assert partial["status"] == "partial" and partial["components"]["weather_factor"] == 1.0 and partial["sources"]["weather"] is None
