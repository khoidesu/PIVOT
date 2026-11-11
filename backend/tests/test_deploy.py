"""Triển khai công khai: mã quản trị cho thao tác phá dữ liệu, URL DB của nhà cung cấp, phục vụ giao diện, seed lần đầu."""
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m
from app.config import Settings, settings
from app.db import SessionLocal
from app.demo.scenarios import run_scenario
from app.main import app, mount_static
from app.seed import reset, seed_if_empty
from tests.conftest import auth

DESTRUCTIVE = [("POST", "/v1/demo/reset"), ("POST", "/v1/demo/retime"), ("POST", "/v1/demo/age-positions"),
               ("POST", "/v1/demo/worker/run"), ("POST", "/v1/demo/scenarios/success/run")]


@pytest.fixture()
def public(monkeypatch):
    monkeypatch.setattr(settings, "admin_key", "s3cret-admin")


def call(client, method, path, key=None):
    headers = auth("dispatch") | ({"X-Admin-Key": key} if key else {})
    return client.request(method, path, headers=headers)


def test_destructive_endpoints_need_the_admin_key_when_public(client, public):
    for method, path in DESTRUCTIVE:
        for key in (None, "wrong"):
            r = call(client, method, path, key)
            assert r.status_code == 403 and r.json()["detail"]["code"] == "ADMIN_KEY_REQUIRED", (path, key)
    assert call(client, "POST", "/v1/demo/retime", "s3cret-admin").status_code == 200
    assert call(client, "POST", "/v1/demo/reset", "s3cret-admin").status_code == 200


def test_admin_key_does_not_replace_the_dispatcher_role(client, public):
    for user in ("shipper_a", "carrier_b", "node_c"):
        r = client.post("/v1/demo/reset", headers=auth(user) | {"X-Admin-Key": "s3cret-admin"})
        assert r.status_code == 403 and r.json()["detail"] != "ADMIN_KEY_REQUIRED"      # đúng khoá nhưng sai vai → vẫn bị chặn


def test_normal_users_are_unaffected_by_the_admin_key(client, public):
    assert client.get("/v1/shipments", headers=auth("shipper_a")).status_code == 200
    assert client.get("/v1/meta", headers=auth("shipper_a")).json()["admin_key_required"] is True


def test_not_required_when_no_key_is_configured(client):
    assert client.get("/v1/meta", headers=auth("shipper_a")).json()["admin_key_required"] is False
    assert call(client, "POST", "/v1/demo/retime").status_code == 200


def test_scenarios_still_pass_with_the_admin_key(seeded, public):
    assert run_scenario("success", lambda: TestClient(app))["passed"]           # kịch bản tự gửi mã khi gọi endpoint demo


def test_provider_database_urls_are_normalised():
    for given in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"):
        assert Settings(database_url=given).database_url == "postgresql+psycopg://u:p@h:5432/db"


def test_security_headers_and_health(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"


def test_static_ui_is_served_without_shadowing_the_api(tmp_path: pathlib.Path):
    (tmp_path / "index.html").write_text("<html>PIVOT-UI</html>")
    app2 = FastAPI()

    @app2.get("/v1/ping")
    def ping():
        return {"pong": True}
    assert mount_static(app2, str(tmp_path)) is True
    c = TestClient(app2)
    assert "PIVOT-UI" in c.get("/").text
    assert c.get("/v1/ping").json() == {"pong": True}                              # API đăng ký trước không bị che
    assert c.get("/khong-co").status_code == 404
    assert mount_static(FastAPI(), str(tmp_path / "missing")) is False and mount_static(FastAPI(), None) is False


def test_seed_if_empty_seeds_once_and_never_touches_user_data(seeded):
    with SessionLocal() as s:
        assert seed_if_empty(s) is None                                              # DB đã có dữ liệu → giữ nguyên
        assert s.query(m.Shipment).count() == 20
        s.query(m.Shipment).filter(m.Shipment.code == "LOT-A-001").one().weight_kg = 777   # "dữ liệu người dùng"
        s.commit()
    with SessionLocal() as s:
        assert seed_if_empty(s) is None
        assert s.execute(select(m.Shipment.weight_kg).where(m.Shipment.code == "LOT-A-001")).scalar_one() == 777
    with SessionLocal() as s:                                                        # DB trống (lần triển khai đầu) → seed
        reset(s)
        s.commit()
        info = seed_if_empty(s)
        s.commit()
        assert info and info["shipments"] == 20


def test_embed_flag_only_removes_frame_protection(client, monkeypatch):
    from app.config import settings
    assert client.get("/healthz").headers["X-Frame-Options"] == "SAMEORIGIN"
    monkeypatch.setattr(settings, "allow_embed", True)
    h = client.get("/healthz").headers
    assert "X-Frame-Options" not in h and h["X-Content-Type-Options"] == "nosniff"

