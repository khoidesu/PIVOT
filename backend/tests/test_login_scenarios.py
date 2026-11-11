"""Kịch bản demo phải xác định kể cả khi đã có người tự đăng nhập (họ có xe/slot riêng có thể bị ghép trúng)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import models as m
from app.db import SessionLocal
from app.demo.scenarios import SCENARIOS, run_scenario
from app.main import app
from tests.conftest import auth


@pytest.mark.parametrize("sid", [s for s, _ in SCENARIOS])
def test_scenarios_pass_even_with_registered_people_present(sid, seeded):
    c = TestClient(app)
    for name, role in (("Hoa", "shipper"), ("Lan", "carrier"), ("Cường", "node_operator")):
        assert c.post("/v1/auth/login", json={"name": name, "role": role}).status_code == 200
    res = run_scenario(sid, lambda: TestClient(app))
    assert res["passed"], [s for s in res["steps"] if not s["ok"]]


def test_running_a_scenario_endpoint_restores_sample_data_for_registered_people(client):
    th = client.post("/v1/auth/login", json={"name": "Hoa", "role": "shipper"}).json()["token"]
    tl = client.post("/v1/auth/login", json={"name": "Lan", "role": "carrier"}).json()["token"]
    td = client.post("/v1/auth/login", json={"name": "Phú", "role": "dispatcher"}).json()["token"]
    r = client.post("/v1/demo/scenarios/race/run", headers=auth(td))
    assert r.status_code == 200 and r.json()["passed"]
    assert len(client.get("/v1/shipments", headers=auth(th)).json()) == 4           # đã được cấp lại sau kịch bản
    assert len(client.get("/v1/vehicles", headers=auth(tl)).json()) == 4
    assert client.get("/v1/me", headers=auth(th)).status_code == 200                # danh tính còn nguyên
