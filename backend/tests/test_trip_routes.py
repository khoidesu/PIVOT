"""Tuyến đường bộ thật (OSRM) lưu theo chuyến + ETA có tín hiệu thật: máy chủ giả, bất biến khi đã chạy, lỗi mạng → tuyến mô phỏng + ETA luật."""
import uuid
from datetime import timedelta

import pytest

from app import models as m
from app.config import settings
from app.db import SessionLocal
from app.eta import signals
from app.sim import gps
from tests.conftest import auth
from tests.helpers import confirm_all, match, run_worker


def fake_network(url, params=None):
    """OSRM giả: đường gấp khúc qua đúng các điểm yêu cầu (lng,lat;…); Open-Meteo giả: mưa vừa."""
    if "/route/v1/" in url:
        wps = [tuple(map(float, c.split(","))) for c in url.rsplit("/", 1)[1].split(";")]
        pts = []
        for (x1, y1), (x2, y2) in zip(wps, wps[1:]):
            pts += [[x1 + (x2 - x1) * i / 20, y1 + (y2 - y1) * i / 20] for i in range(20)]
        pts.append(list(wps[-1]))
        return {"code": "Ok", "routes": [{"distance": 30000.0, "duration": 2400.0, "geometry": {"coordinates": pts},
                                          "legs": [{"duration": 600.0}] * (len(wps) - 1)}]}
    return {"current": {"time": "2026-11-11T10:00", "precipitation": 4.0, "weather_code": 63, "wind_speed_10m": 10.0}}


@pytest.fixture()
def net(monkeypatch):
    monkeypatch.setattr(settings, "signals_enabled", True)
    signals.clear_cache()
    monkeypatch.setattr(signals, "_get_json", fake_network)
    yield
    signals.clear_cache()


def _confirmed(client):
    return confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])


def test_road_route_is_stored_once_and_drawn_instead_of_the_interpolated_line(client, net):
    prop = _confirmed(client)
    before = client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()
    assert before["route_source"] == "simulated" and before["eta_signals"]["status"] == "fallback"   # chưa lấy đường: nói thật, không bịa
    r = client.post(f"/v1/tracking/{prop['id']}/road-route", headers=auth("shipper_a")).json()
    assert r["route_source"] == "osrm" and r["distance_km"] == 30.0
    after = client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()
    assert after["route_source"] == "osrm" and len(after["route"]) > len(before["route"]) and after["total_km"] != before["total_km"]
    again = client.post(f"/v1/tracking/{prop['id']}/road-route", headers=auth("shipper_a")).json()
    assert again["route_source"] == "osrm"
    with SessionLocal() as s:
        assert s.query(m.TripRoute).count() == 1                                                       # idempotent


def test_eta_signals_apply_weather_and_label_sources(client, net):
    prop = _confirmed(client)
    client.post(f"/v1/tracking/{prop['id']}/road-route", headers=auth("shipper_a"))
    e = client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()["eta_signals"]
    assert e["status"] == "ok" and e["method"] == "rule-based+signals" and e["sources"] == {"route": "osrm", "weather": "open-meteo", "traffic": None}
    assert e["components"]["weather_factor"] > 1.0 and e["minutes_p90"] > e["minutes_p50"] > 0 and e["simulated_positions"] is True


def test_network_down_keeps_simulated_route_and_rule_eta(client, monkeypatch):
    monkeypatch.setattr(settings, "signals_enabled", True)
    signals.clear_cache()

    def down(url, params=None):
        raise TimeoutError("offline")
    monkeypatch.setattr(signals, "_get_json", down)
    prop = _confirmed(client)
    assert client.post(f"/v1/tracking/{prop['id']}/road-route", headers=auth("shipper_a")).json()["route_source"] == "simulated"
    d = client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()
    assert d["route_source"] == "simulated" and d["eta"] is not None and d["eta_signals"]["p50"] is None
    signals.clear_cache()


def test_disabled_signals_report_disabled_and_never_touch_the_network(client, monkeypatch):
    monkeypatch.setattr(signals, "_get_json", lambda *a, **k: pytest.fail("network must not be called"))
    prop = _confirmed(client)                                       # conftest đặt PIVOT_SIGNALS_ENABLED=false
    assert client.post(f"/v1/tracking/{prop['id']}/road-route", headers=auth("shipper_a")).json()["route_source"] == "simulated"
    assert client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()["eta_signals"]["status"] == "disabled"


def test_route_geometry_is_frozen_once_the_trip_runs_and_sim_still_reaches_the_gate(client, net):
    prop = _confirmed(client)
    assert client.post(f"/v1/sim/{prop['id']}/start?speedup=20000", headers=auth("carrier_b")).status_code == 200   # sim.start lưu đường bộ thật
    run_worker(client)
    d1 = client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()
    assert d1["route_source"] == "osrm"
    with SessionLocal() as s:
        t0 = s.get(m.SimTrip, uuid.UUID(prop["id"])).updated_at
    for i in range(1, 4):                                           # tăng tốc cao → tới cổng ICD ngay lần đầu; các lần sau là no-op
        with SessionLocal() as s:
            gps.tick(s, t0 + timedelta(seconds=i * 20)); s.commit()
        run_worker(client)
    d2 = client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a")).json()
    assert d2["route"] == d1["route"]                               # hình học bất biến suốt chuyến
    assert {x["code"] for x in d2["milestones"] if x["reached"]} >= {"AT_PICKUP", "DEPARTED_PICKUP", "AT_ICD_GATE"}
    assert client.post(f"/v1/tracking/{prop['id']}/road-route", headers=auth("shipper_a")).json()["route_source"] == "osrm"


def test_trip_eta_carries_live_traffic_and_never_exposes_the_token(client, net, monkeypatch):
    monkeypatch.setattr(settings, "mapbox_token", "pk.SECRET-TEST-TOKEN")

    def both(url, params=None):
        if "api.mapbox.com" in url:
            n = 9
            coords = [[106.74 + 0.01 * i, 10.9 - 0.005 * i] for i in range(n)]
            return {"code": "Ok", "routes": [{"duration": 3000.0 if "driving-traffic" in url else 2000.0, "distance": 30000.0,
                                              "geometry": {"coordinates": coords},
                                              "legs": [{"annotation": {"congestion": ["low"] * 4 + ["heavy"] * 4}}]}]}
        return fake_network(url, params)
    monkeypatch.setattr(signals, "_get_json", both)
    prop = _confirmed(client)
    client.post(f"/v1/tracking/{prop['id']}/road-route", headers=auth("shipper_a"))
    r = client.get(f"/v1/tracking/{prop['id']}", headers=auth("shipper_a"))
    e = r.json()["eta_signals"]
    assert e["sources"]["traffic"] == "mapbox" and e["components"]["traffic_kind"] == "live" and e["components"]["traffic_factor"] == pytest.approx(1.5, abs=0.01)
    assert {g["level"] for g in e["traffic"]["segments"]} == {"low", "heavy"}
    assert "SECRET" not in r.text                                    # khoá API không bao giờ ra giao diện
