"""Khoá Gemini dùng chung cho cả web: không lộ khoá, và giới hạn lượt theo tài khoản + IP + toàn hệ thống. Không gọi mạng thật."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from starlette.requests import Request

from app.config import settings
from app.intake.extractor import UsageGuard, build_image_extractor, image_guard, reset_guards
from app.main import app
from app.routers.intake import client_ip, get_image_extractor
from tests.conftest import auth
from tests.test_intake_image import B64, FakeGemini, jpeg

NOW = datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- bộ đếm
def test_ip_limit_stops_renaming_to_get_more_quota():
    g = UsageGuard(per_user_day=3, per_user_min=10, global_day=100, per_ip_day=4, per_ip_min=10)
    got = [g.acquire(f"user-{i}", NOW, "1.2.3.4") for i in range(6)]                    # mỗi lần một "tài khoản" mới, cùng IP
    assert got == [None, None, None, None, "ip_day", "ip_day"]
    assert g.acquire("user-9", NOW, "5.6.7.8") is None                                   # IP khác vẫn được
    assert g.remaining("user-0", "1.2.3.4") == 0 and g.remaining("user-9", "5.6.7.8") == 2


def test_minute_limits_per_ip_and_whole_system_then_recover():
    g = UsageGuard(per_user_day=50, per_user_min=50, global_day=500, per_ip_day=50, per_ip_min=2, global_min=3)
    assert [g.acquire("a", NOW, "1.1.1.1") for _ in range(3)] == [None, None, "ip_minute"]
    assert g.acquire("b", NOW, "2.2.2.2") is None
    assert g.acquire("c", NOW, "3.3.3.3") == "global_minute"                             # 3 lượt/phút cho cả hệ thống
    assert g.acquire("c", NOW + timedelta(seconds=61), "3.3.3.3") is None                # sang phút sau thì được


def test_blocked_calls_cost_nothing_and_failures_are_refunded():
    g = UsageGuard(per_user_day=1, per_user_min=5, global_day=10, per_ip_day=1, per_ip_min=5)
    assert g.acquire("a", NOW, "ip") is None
    assert g.acquire("b", NOW, "ip") == "ip_day" and g._users.get("b", 0) == 0 and g._total == 1
    g.refund("a", "ip")                                                                   # mô hình lỗi → hoàn lượt cả tài khoản lẫn IP
    assert g.acquire("b", NOW, "ip") is None


def test_client_ip_trusts_only_the_proxy_added_entry(monkeypatch):
    def req(xff: str | None):
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        return Request({"type": "http", "headers": headers, "client": ("10.0.0.9", 1234)})
    monkeypatch.setattr(settings, "trust_proxy", False)
    assert client_ip(req("6.6.6.6")) == "10.0.0.9"                                       # không sau proxy: bỏ qua header
    monkeypatch.setattr(settings, "trust_proxy", True)
    assert client_ip(req("6.6.6.6, 203.0.113.7")) == "203.0.113.7"                        # phần đầu do trình duyệt tự gửi → không tin
    assert client_ip(req(None)) == "10.0.0.9"


# ---------------------------------------------------------------- qua API
@pytest.fixture()
def fake(client):
    reset_guards()
    f = FakeGemini()
    app.dependency_overrides[get_image_extractor] = lambda: f
    yield f
    app.dependency_overrides.pop(get_image_extractor, None)
    reset_guards()


def test_new_names_on_the_same_network_share_one_image_quota(client, fake, monkeypatch):
    monkeypatch.setattr(settings, "llm_image_per_ip_day", 2)
    reset_guards()
    codes = []
    for key in ("shipper_a", "carrier_b", "shipper_a2"):                                 # ba tài khoản khác nhau, cùng một máy
        r = client.post("/v1/intake/drafts/file", headers=auth(key), json={"file_base64": B64(jpeg())})
        codes.append(r.json()["detail"]["code"] if r.status_code != 200 else 200)
        image_guard(settings)._recent.clear()
    assert codes == [200, 200, "IMAGE_QUOTA_IP_DAY"] and fake.calls == 2


def test_the_key_never_reaches_the_browser(client, monkeypatch):
    secret = "AQ.TEST-SECRET-KEY-DO-NOT-LEAK"
    monkeypatch.setattr(settings, "gemini_api_key", secret)
    reset_guards()
    seen = {}

    def google(req: httpx.Request):  # Google trả lỗi có nhắc lại khoá — máy chủ không được chuyển nguyên văn cho trình duyệt
        seen["header"] = req.headers.get("x-goog-api-key")
        return httpx.Response(400, json={"error": {"message": f"API key {secret} is invalid"}})
    ex = build_image_extractor(settings)
    ex._transport = httpx.MockTransport(google)
    for m in [ex.model, *ex.fallbacks]:
        assert secret not in m
    app.dependency_overrides[get_image_extractor] = lambda: ex
    try:
        r = client.post("/v1/intake/drafts/file", headers=auth("shipper_a"), json={"file_base64": B64(jpeg())})
        meta = client.get("/v1/meta", headers=auth("shipper_a"))
    finally:
        app.dependency_overrides.pop(get_image_extractor, None)
        reset_guards()
    assert seen["header"] == secret and secret not in str(httpx.URL(settings.gemini_url))  # khoá chỉ đi trong header tới Google
    assert r.status_code == 503 and secret not in r.text
    assert meta.json()["image_intake_enabled"] is True and secret not in meta.text and "AQ." not in json.dumps(meta.json())
