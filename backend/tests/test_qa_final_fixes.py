"""Hồi quy cho QA_FINAL_REPORT (13/11): QA-03 (chỉ chủ hàng gọi API nhập liệu), QA-04 (NaN/Infinity → 422, không 500, không lưu),
QA-08 (báo lặp cùng loại sự cố không mở ngoại lệ thứ hai khi ngoại lệ cũ còn mở)."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app import models as m
from app.config import settings
from app.db import SessionLocal
from app.intake.extractor import image_guard, reset_guards, usage_guard
from app.main import app
from app.routers.intake import get_extractor, get_image_extractor
from tests.conftest import auth
from tests.helpers import confirm_all, lot_id, match, post_event, run_worker
from tests.test_intake_image import B64, FakeGemini, jpeg
from tests.test_intake_pdf import TEXT, make_pdf

NOW = datetime.now(timezone.utc)
ROLES = ("shipper_a", "carrier_b", "node_c", "dispatch")
BAD_NUMBERS = ("NaN", "Infinity", "-Infinity", "1e309", "-1e309")


# ================================================================ QA-03
class SpyExtractor:
    """Bộ luật thật, có đếm số lần được gọi."""

    def __init__(self):
        from app.intake.extractor import build_extractor
        self.calls, self._real = 0, build_extractor(settings)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def extract(self, text, now, locations):
        self.calls += 1
        return self._real.extract(text, now, locations)


@pytest.fixture()
def spies(client):
    reset_guards()
    img, txt = FakeGemini(), SpyExtractor()
    app.dependency_overrides[get_image_extractor] = lambda: img
    app.dependency_overrides[get_extractor] = lambda: txt
    yield img, txt
    app.dependency_overrides.pop(get_image_extractor, None)
    app.dependency_overrides.pop(get_extractor, None)
    reset_guards()


def _call_intake(client, user: str, endpoint: str):
    if endpoint == "drafts":
        return client.post("/v1/intake/drafts", json={"text": "12 tấn hàng khô từ Sóng Thần"}, headers=auth(user))
    if endpoint == "file":
        return client.post("/v1/intake/drafts/file", json={"file_base64": B64(make_pdf([TEXT]))}, headers=auth(user))
    return client.post("/v1/intake/drafts/image", json={"image_base64": B64(jpeg())}, headers=auth(user))


@pytest.mark.parametrize("endpoint", ["drafts", "file", "image"])
@pytest.mark.parametrize("user", ROLES)
def test_qa03_only_shipper_may_call_intake(client, spies, user, endpoint):
    r = _call_intake(client, user, endpoint)
    if user == "shipper_a":
        assert r.status_code == 200, r.text
    else:
        assert r.status_code == 403, r.text


@pytest.mark.parametrize("endpoint", ["drafts", "file", "image"])
def test_qa03_forbidden_calls_spend_no_quota_and_read_nothing(client, spies, endpoint):
    img, txt = spies
    for user in ("carrier_b", "node_c", "dispatch"):
        assert _call_intake(client, user, endpoint).status_code == 403
    assert img.calls == 0 and txt.calls == 0                                        # không đọc tệp/tin
    for guard in (image_guard(settings), usage_guard(settings)):                     # không tính lượt nào
        assert guard._users == {} and guard._ips == {} and guard._total == 0
    with SessionLocal() as s:                                                         # không ghi vết bản nháp
        assert s.execute(select(func.count()).select_from(m.Event).where(m.Event.event_type == "INTAKE_DRAFT_CREATED")).scalar_one() == 0


# ================================================================ QA-04
def _raw(client, method: str, url: str, body: dict, field_path: tuple[str, ...], token: str, user: str):
    """Gửi JSON thô có số không hữu hạn ở `field_path` (trình duyệt không gửi được, chỉ client gọi thẳng API)."""
    target = body
    for k in field_path[:-1]:
        target = target[k]
    target[field_path[-1]] = "__BAD__"
    raw = json.dumps(body).replace('"__BAD__"', token)
    return client.request(method, url, content=raw, headers={**auth(user), "Content-Type": "application/json"})


def _count(model) -> int:
    with SessionLocal() as s:
        return s.execute(select(func.count()).select_from(model)).scalar_one()


def _lot_body(client, code: str) -> dict:
    locs = client.get("/v1/locations", headers=auth("shipper_a")).json()
    return {"code": code, "cargo_type": "dry", "weight_kg": 9000, "volume_m3": 22,
            "origin_location_id": next(l["id"] for l in locs if l["kind"] == "industrial_zone"),
            "dest_location_id": next(l["id"] for l in locs if l["kind"] == "icd"),
            "ready_at": (NOW + timedelta(hours=1)).isoformat(), "pickup_deadline": (NOW + timedelta(hours=4)).isoformat(),
            "cutoff_at": (NOW + timedelta(hours=12)).isoformat()}


def _assert_422(r):
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]                                                       # định dạng lỗi 422 mặc định của FastAPI giữ nguyên
    assert isinstance(detail, list) or isinstance(detail, dict)


@pytest.mark.parametrize("token", BAD_NUMBERS)
@pytest.mark.parametrize("field", ["weight_kg", "volume_m3"])
def test_qa04_create_lot_rejects_non_finite_numbers(client, field, token):
    before = _count(m.Shipment)
    _assert_422(_raw(client, "POST", "/v1/shipments", _lot_body(client, f"QA-{field}-{abs(hash(token)) % 999}"), (field,), token, "shipper_a"))
    assert _count(m.Shipment) == before


@pytest.mark.parametrize("token", BAD_NUMBERS)
@pytest.mark.parametrize("field", ["weight_kg", "volume_m3"])
def test_qa04_edit_lot_rejects_non_finite_numbers(client, field, token):
    lot = next(s for s in client.get("/v1/shipments", headers=auth("shipper_a")).json() if s["code"] == "LOT-A-001")
    _assert_422(_raw(client, "PATCH", f"/v1/shipments/{lot['id']}", {"version": lot["version"]}, (field,), token, "shipper_a"))
    after = next(s for s in client.get("/v1/shipments", headers=auth("shipper_a")).json() if s["id"] == lot["id"])
    assert after[field] == lot[field] and after["version"] == lot["version"]


@pytest.mark.parametrize("field,limit", [("weight_kg", 100_000), ("volume_m3", 500)])
def test_qa04_lot_size_has_an_upper_bound(client, field, limit):
    assert client.post("/v1/shipments", json=_lot_body(client, "QA-CAP-1") | {field: limit + 1}, headers=auth("shipper_a")).status_code == 422
    assert client.post("/v1/shipments", json=_lot_body(client, "QA-CAP-2") | {field: limit}, headers=auth("shipper_a")).status_code == 201


def _event_body(entity_id: str, event_type: str, payload: dict, entity_type: str = "proposal") -> dict:
    return {"entity_type": entity_type, "entity_id": entity_id, "event_type": event_type, "payload": payload,
            "occurred_at": NOW.isoformat(), "source_system": "qa", "source_event_id": str(uuid.uuid4())}


@pytest.mark.parametrize("token", BAD_NUMBERS)
def test_qa04_event_payloads_reject_non_finite_numbers(client, token):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    veh = client.get("/v1/vehicles", headers=auth("carrier_b")).json()[0]["id"]
    cases = [
        (_event_body(prop["id"], "TRIP_COMPLETED", {"actual_empty_km": 1}), ("payload", "actual_empty_km")),
        (_event_body(prop["id"], "ETA_UPDATED", {"delay_minutes": 1}), ("payload", "delay_minutes")),
        (_event_body(prop["id"], "INCIDENT_REPORTED", {"kind": "BREAKDOWN", "delay_minutes": 1}), ("payload", "delay_minutes")),
        (_event_body(veh, "VEHICLE_POSITION", {"lat": 10.9, "lng": 106.7}, "vehicle"), ("payload", "lat")),
        (_event_body(veh, "VEHICLE_POSITION", {"lat": 10.9, "lng": 106.7, "speed_kmh": 30}, "vehicle"), ("payload", "speed_kmh")),
        (_event_body(prop["id"], "SOMETHING_UNKNOWN", {"x": {"deep": [1]}}), ("payload", "x", "deep")),  # loại lạ cũng không được lưu NaN
    ]
    before = _count(m.Event)
    for body, path in cases:
        if path[-1] == "deep":
            body["payload"]["x"]["deep"] = "__BAD__"
            raw = json.dumps(body).replace('"__BAD__"', token)
            r = client.post("/v1/events", content=raw, headers={**auth("carrier_b"), "Content-Type": "application/json"})
        else:
            r = _raw(client, "POST", "/v1/events", body, path, token, "carrier_b")
        _assert_422(r)
    assert _count(m.Event) == before


@pytest.mark.parametrize("token", BAD_NUMBERS)
@pytest.mark.parametrize("field", ["km", "rain_mm_h", "wind_kmh"])
def test_qa04_eta_predict_rejects_non_finite_numbers(client, field, token):
    body = {"depart_at": NOW.isoformat(), "km": 25}
    _assert_422(_raw(client, "POST", "/v1/eta/predict", body, (field,), token, "carrier_b"))


def test_qa04_validation_errors_never_crash_the_422_handler(client):
    # chuỗi mã hoá không hợp lệ + số không hữu hạn trong cùng một lỗi → vẫn 422 JSON hợp lệ
    r = client.post("/v1/shipments", content='{"weight_kg": NaN, "volume_m3": [Infinity, -Infinity]}',
                    headers={**auth("shipper_a"), "Content-Type": "application/json"})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)
    assert "NaN" not in r.text or '"nan"' in r.text.lower()                           # không có token NaN trần trong JSON trả về
    json.loads(r.text, parse_constant=lambda c: (_ for _ in ()).throw(AssertionError(f"non-JSON constant {c}")))


def test_qa04_sim_speedup_rejects_nan(client):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    assert client.post(f"/v1/sim/{prop['id']}/start?speedup=nan", headers=auth("carrier_b")).status_code == 422
    assert client.post(f"/v1/sim/{prop['id']}/start?speedup=inf", headers=auth("carrier_b")).status_code == 422


# ================================================================ QA-08
def _excs(client, pid: str, user: str = "shipper_a") -> list[dict]:
    return [e for e in client.get("/v1/exceptions", headers=auth(user)).json() if e["proposal_id"] == pid]


def _notifications() -> int:
    return _count(m.Notification)


@pytest.mark.parametrize("event_type,payload,reporter,category", [
    ("INCIDENT_REPORTED", {"kind": "BREAKDOWN"}, "carrier_b", "BREAKDOWN"),
    ("CARGO_DAMAGE_REPORTED", {"note": "Thùng móp"}, "node_c", "CARGO_DAMAGE"),
])
def test_qa08_repeat_report_merges_into_the_open_exception(client, event_type, payload, reporter, category):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    assert post_event(client, reporter, prop["id"], event_type, payload).status_code == 202
    run_worker(client)
    [first] = _excs(client, prop["id"])
    n_notes, n_tasks = _notifications(), _count(m.ExceptionTask)

    assert post_event(client, reporter, prop["id"], event_type, {**payload, "note": "báo lại"}).status_code == 202  # khác source_event_id
    run_worker(client)
    [same] = _excs(client, prop["id"])
    assert same["id"] == first["id"] and same["status"] == "open" and same["exc_type"] == category
    assert _notifications() == n_notes and _count(m.ExceptionTask) == n_tasks            # không thêm playbook/SLA/thông báo
    assert same["detail"]["repeat_reports"] == 1 and same["detail"]["last_note"] == "báo lại"
    with SessionLocal() as s:                                                            # sự kiện vẫn được ghi nhận, không bị nuốt
        evs = s.execute(select(m.Event).where(m.Event.entity_id == uuid.UUID(prop["id"]), m.Event.event_type == event_type)).scalars().all()
    assert len(evs) == 2 and all(e.quality_status == "applied" for e in evs)

    # đã xử lý xong mà báo lại → ngoại lệ mới
    r = client.post(f"/v1/exceptions/{first['id']}/resolve", json={"resolution": "accept_delay"}, headers=auth("shipper_a"))
    assert r.status_code == 200, r.text
    assert post_event(client, reporter, prop["id"], event_type, payload).status_code == 202
    run_worker(client)
    rows = _excs(client, prop["id"])
    assert sorted(e["status"] for e in rows if e["exc_type"] == category) == ["open", "resolved"]


def test_qa08_same_source_event_stays_idempotent_and_other_kinds_still_open(client):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    for _ in range(3):
        post_event(client, "carrier_b", prop["id"], "INCIDENT_REPORTED", {"kind": "BREAKDOWN"}, source_event_id="bd-dup")
    post_event(client, "carrier_b", prop["id"], "INCIDENT_REPORTED", {"kind": "TRAFFIC_INCIDENT", "delay_minutes": 20})
    run_worker(client); run_worker(client)
    rows = _excs(client, prop["id"])
    assert sorted(e["exc_type"] for e in rows) == ["BREAKDOWN", "TRAFFIC_INCIDENT"]
    assert next(e for e in rows if e["exc_type"] == "BREAKDOWN")["detail"].get("repeat_reports") is None  # gửi trùng id ≠ báo lặp


def test_qa08_other_trips_are_not_merged(client):
    p1 = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    p2 = confirm_all(client, match(client, "shipper_a", "LOT-A-002")["proposals"][0])
    for p in (p1, p2):
        post_event(client, "carrier_b", p["id"], "INCIDENT_REPORTED", {"kind": "BREAKDOWN"})
    run_worker(client)
    assert len(_excs(client, p1["id"])) == 1 and len(_excs(client, p2["id"])) == 1


def test_qa08_sim_breakdown_mode_yields_one_breakdown_and_one_delay_risk(client):
    from tests.test_eta import _running, _tick
    prop, t0 = _running(client)
    _tick(t0, 5); run_worker(client)
    for i, mode in enumerate(("breakdown", "normal", "breakdown"), 1):                # bật hỏng xe 2 lần → bộ giả lập báo 2 sự kiện khác id
        assert client.post(f"/v1/sim/{prop['id']}/mode", json={"mode": mode}, headers=auth("carrier_b")).status_code == 200
        for j in range(3):
            _tick(t0, 5 + i * 15 + j * 5); run_worker(client)
    with SessionLocal() as s:
        reports = s.execute(select(func.count()).select_from(m.Event).where(
            m.Event.entity_id == uuid.UUID(prop["id"]), m.Event.event_type == "INCIDENT_REPORTED")).scalar_one()
    assert reports >= 2                                                                 # đúng là có báo lặp
    rows = _excs(client, prop["id"])
    assert [e["exc_type"] for e in rows].count("BREAKDOWN") == 1
    assert [e["exc_type"] for e in rows].count("DELAY_RISK") == 1


def test_qa03_role_is_checked_before_the_body(client):
    assert client.post("/v1/intake/drafts/file", json={"file_base64": "x"}, headers=auth("carrier_b")).status_code == 403
    assert client.post("/v1/intake/drafts", json={}, headers=auth("node_c")).status_code == 403


def test_qa08_worse_repeat_report_raises_severity_once(client):
    prop = confirm_all(client, match(client, "shipper_a", "LOT-A-001")["proposals"][0])
    post_event(client, "carrier_b", prop["id"], "INCIDENT_REPORTED", {"kind": "TRAFFIC_INCIDENT", "delay_minutes": 10})
    run_worker(client)
    [ex] = _excs(client, prop["id"])
    assert ex["severity"] == "medium"
    n0 = _notifications()
    post_event(client, "carrier_b", prop["id"], "INCIDENT_REPORTED", {"kind": "TRAFFIC_INCIDENT", "delay_minutes": 5})  # nhẹ hơn: im lặng
    run_worker(client)
    assert _notifications() == n0 and _excs(client, prop["id"])[0]["severity"] == "medium"
    post_event(client, "carrier_b", prop["id"], "INCIDENT_REPORTED", {"kind": "TRAFFIC_INCIDENT", "delay_minutes": 120})  # nặng hơn: nâng mức
    run_worker(client)
    [up] = _excs(client, prop["id"])
    assert up["id"] == ex["id"] and up["severity"] == "critical" and up["detail"]["delay_minutes"] == 120
    assert up["detail"]["repeat_reports"] == 2 and _notifications() > n0
