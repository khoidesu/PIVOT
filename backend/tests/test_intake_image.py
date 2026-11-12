"""Nhập liệu từ ẢNH bằng Gemini: không gọi mạng thật (bộ giả / MockTransport)."""
import base64
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.intake.extractor import GeminiExtractor, reset_guards, sniff_image, strip_jpeg_metadata
from app.main import app
from app.routers.intake import get_image_extractor
from tests.conftest import auth

NOW = datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc)
LOCS = [{"id": "1", "name": "KCN Sóng Thần (mô phỏng)", "kind": "industrial_zone"}, {"id": "3", "name": "ICD Cảng C (mô phỏng)", "kind": "icd"}]
TRANSCRIPT = "Hàng khô 12 tấn 30 khối\nKCN Sóng Thần -> ICD Cảng C\nSẵn sàng 14h 12/11, hạn lấy hàng 17h 12/11, cut-off 23h 12/11\nGiá 2 triệu"
FIELDS = {"cargo_type": {"value": "dry", "quote": "Hàng khô"}, "weight_kg": {"value": 12000, "quote": "12 tấn"},
          "volume_m3": {"value": 30, "quote": "30 khối"}, "origin": {"value": "KCN Sóng Thần (mô phỏng)", "quote": "KCN Sóng Thần"},
          "dest": {"value": "ICD Cảng C (mô phỏng)", "quote": "ICD Cảng C"},
          "ready_at": {"value": "2026-11-12T14:00:00+07:00", "quote": "14h 12/11"},
          "pickup_deadline": {"value": "2026-11-12T17:00:00+07:00", "quote": "17h 12/11"},
          "cutoff_at": {"value": "2026-11-12T23:00:00+07:00", "quote": "23h 12/11"},
          "price_vnd": {"value": 2000000, "quote": "Giá 2 triệu"}}


def jpeg(extra: bytes = b"") -> bytes:  # JPEG tối thiểu (đủ để nhận dạng + phân tích đoạn), không cần giải mã được
    return b"\xff\xd8" + extra + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00" + b"\x12" * 200 + b"\xff\xd9"


B64 = lambda b: base64.b64encode(b).decode()  # noqa: E731


class FakeGemini:
    name = "gemini:fake"

    def __init__(self, result="ok"):
        self.result, self.calls, self.seen = result, 0, None

    def extract_image(self, data, mime, now, locations):
        self.calls += 1
        self.seen = (data, mime)
        return None if self.result is None else (FIELDS, TRANSCRIPT)


@pytest.fixture()
def fake(client):
    reset_guards()
    f = FakeGemini()
    app.dependency_overrides[get_image_extractor] = lambda: f
    yield f
    app.dependency_overrides.pop(get_image_extractor, None)
    reset_guards()


def post(client, user, data: bytes | str, key="shipper_a"):
    return client.post("/v1/intake/drafts/image", headers=auth(user or key), json={"image_base64": data if isinstance(data, str) else B64(data)})


def test_image_draft_has_transcript_and_every_field_needs_review(client, fake):
    r = post(client, "shipper_a", jpeg())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["is_draft_only"] and d["source"]["kind"] == "image" and d["transcript"] == TRANSCRIPT
    assert d["extractor"]["name"] == "gemini:fake" and d["image_quota_remaining"] == 2
    for k in ("cargo_type", "weight_kg", "origin", "cutoff_at", "price_vnd"):
        assert d["fields"][k]["status"] == "needs_review" and "FROM_IMAGE" in d["fields"][k]["notes"]
    assert d["fields"]["weight_kg"]["value"] == 12000 and d["fields"]["origin"]["display"] == "KCN Sóng Thần (mô phỏng)"   # vẫn qua kiểm tra bằng luật (khớp địa điểm trong DB)
    assert set(d["needs_review"]) >= {"cargo_type", "weight_kg", "ready_at"}


def test_quotes_are_checked_against_the_transcript_not_trusted(client, fake, monkeypatch):
    bad = dict(FIELDS, weight_kg={"value": 99000, "quote": "99 tấn không có trong ảnh"})
    monkeypatch.setattr(fake, "extract_image", lambda *a: (bad, TRANSCRIPT))
    d = post(client, "shipper_a", jpeg()).json()
    assert d["fields"]["weight_kg"]["value"] is None and "QUOTE_NOT_FOUND_IN_SOURCE" in d["fields"]["weight_kg"]["notes"]


def _clear_minute_window():
    from app.config import settings
    from app.intake.extractor import image_guard
    image_guard(settings)._recent.clear()


def test_daily_limit_is_three_images_per_user_then_429_without_calling_the_model(client, fake):
    codes = []
    for _ in range(5):
        codes.append(post(client, "shipper_a", jpeg()).status_code)
        _clear_minute_window()                                               # bỏ giới hạn theo phút để chỉ thử giới hạn theo ngày
    assert codes == [200, 200, 200, 429, 429]
    assert post(client, "shipper_a", jpeg()).json()["detail"]["code"] == "IMAGE_QUOTA_USER_DAY"
    assert fake.calls == 3                                                   # hết lượt thì không gọi mô hình
    assert post(client, "carrier_b", jpeg()).status_code == 200              # người khác có lượt riêng


def test_burst_is_limited_per_minute(client, fake):
    assert [post(client, "shipper_a", jpeg()).status_code for _ in range(3)] == [200, 200, 429]
    assert post(client, "shipper_a", jpeg()).json()["detail"]["code"] == "IMAGE_QUOTA_USER_MINUTE"


def test_failed_reading_gives_the_attempt_back(client, fake):
    fake.result = None
    for _ in range(4):
        r = post(client, "shipper_a", jpeg())
        assert r.status_code == 503 and r.json()["detail"]["code"] == "IMAGE_UNREADABLE"
        _clear_minute_window()
    fake.result = "ok"
    assert post(client, "shipper_a", jpeg()).status_code == 200              # lỗi phía máy chủ không bị tính lượt


def test_files_are_checked_by_content_size_and_encoding(client, fake):
    assert post(client, "shipper_a", b"MZ\x90\x00" + b"\x00" * 300).status_code == 415            # không phải ảnh (vd tệp thực thi đổi đuôi)
    assert post(client, "shipper_a", b"<svg xmlns='http://www.w3.org/2000/svg'>" + b" " * 200 + b"<script>alert(1)</script></svg>").status_code == 415
    assert post(client, "shipper_a", "%%%không-phải-base64%%%" + "A" * 120).status_code == 422
    assert post(client, "shipper_a", jpeg(b"\xff\xfe\x0f\xa0" + b"A" * 4000 + b"")[:2] + b"\x00" * 4_100_000).status_code in (413, 415)
    big = b"\xff\xd8\xff" + b"\x00" * 4_100_000
    assert post(client, "shipper_a", big).status_code == 413
    assert fake.calls == 0


def test_png_and_webp_are_accepted_by_signature(client, fake):
    assert sniff_image(b"\x89PNG\r\n\x1a\n" + b"x" * 20) == "image/png"
    assert sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert post(client, "shipper_a", b"\x89PNG\r\n\x1a\n" + b"x" * 200).status_code == 200


def test_exif_gps_is_stripped_before_the_image_leaves_the_server(client, fake):
    exif = b"\xff\xe1" + (2 + 40).to_bytes(2, "big") + b"Exif\x00\x00GPS-LATITUDE-10.123".ljust(40, b"x")
    data = jpeg(exif)
    assert b"GPS-LATITUDE" in data
    assert b"GPS-LATITUDE" not in strip_jpeg_metadata(data) and strip_jpeg_metadata(data).startswith(b"\xff\xd8\xff\xe0")
    post(client, "shipper_a", data)
    assert b"GPS-LATITUDE" not in fake.seen[0] and fake.seen[1] == "image/jpeg"
    assert strip_jpeg_metadata(b"\x89PNG....") == b"\x89PNG...."


def test_only_shipper_or_carrier_may_use_it_and_it_can_be_disabled(client, fake):
    assert post(client, "node_c", jpeg()).status_code == 403
    assert post(client, "dispatch", jpeg()).status_code == 403
    app.dependency_overrides[get_image_extractor] = lambda: None
    r = post(client, "shipper_a", jpeg())
    assert r.status_code == 501 and r.json()["detail"]["code"] == "IMAGE_INTAKE_DISABLED"
    assert client.get("/v1/meta", headers=auth("shipper_a")).json()["image_intake_enabled"] is False   # test không có khoá


def test_draft_from_image_creates_nothing_and_audit_has_no_image_or_transcript(client, fake):
    from sqlalchemy import select
    from app import models as m
    from app.db import SessionLocal
    before = len(client.get("/v1/shipments", headers=auth("shipper_a")).json())
    d = post(client, "shipper_a", jpeg()).json()
    assert len(client.get("/v1/shipments", headers=auth("shipper_a")).json()) == before and client.get("/v1/proposals", headers=auth("shipper_a")).json() == []
    with SessionLocal() as s:
        ev = s.execute(select(m.Event).where(m.Event.event_type == "INTAKE_DRAFT_CREATED")).scalars().one()
        raw = json.dumps(ev.payload, ensure_ascii=False)
        assert ev.payload["image"]["mime"] == "image/jpeg" and "12 tấn" in raw and "2 triệu" not in raw and "Hàng khô 12 tấn 30 khối\nKCN" not in raw
    assert d["draft_id"]


# ---------------------------------------------------------------- bộ gọi Gemini cho ảnh
def test_gemini_image_request_shape_and_fail_closed():
    seen = {}

    def ok(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("x-goog-api-key"), json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps({**FIELDS, "evil": {"value": 1, "quote": "x"}, "transcript": TRANSCRIPT})}]}}]})
    ex = GeminiExtractor("secret", "gm", transport=httpx.MockTransport(ok))
    fields, transcript = ex.extract_image(jpeg(), "image/jpeg", NOW, LOCS)
    assert transcript == TRANSCRIPT and "evil" not in fields and fields["weight_kg"]["value"] == 12000
    assert "secret" not in seen["url"] and seen["key"] == "secret"
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg" and base64.b64decode(parts[0]["inline_data"]["data"]) == jpeg()
    assert "transcript" in seen["body"]["generationConfig"]["responseSchema"]["properties"]
    assert "KHÔNG TIN CẬY" in seen["body"]["systemInstruction"]["parts"][0]["text"]
    for handler in (lambda r: httpx.Response(500), lambda r: httpx.Response(200, json={"candidates": []}),
                    lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps({**FIELDS})}]}}]}),   # thiếu transcript
                    lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "không phải json"}]}}]})):
        assert GeminiExtractor("k", "m", transport=httpx.MockTransport(handler)).extract_image(jpeg(), "image/jpeg", NOW, LOCS) is None


def test_fields_the_model_missed_are_filled_by_rules_on_the_transcript(client, fake, monkeypatch):
    partial = {k: v for k, v in FIELDS.items() if k not in ("origin", "dest", "cutoff_at")}
    monkeypatch.setattr(fake, "extract_image", lambda *a: (dict(partial), TRANSCRIPT))
    d = post(client, "shipper_a", jpeg()).json()
    assert d["fields"]["origin"]["display"] == "KCN Sóng Thần (mô phỏng)" and d["fields"]["dest"]["display"] == "ICD Cảng C (mô phỏng)"
    assert d["fields"]["cutoff_at"]["value"] is not None and d["fields"]["cutoff_at"]["status"] == "needs_review"
