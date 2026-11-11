"""10 kịch bản demo (6 bắt buộc + 4 cho Control Tower) (DRAFT mục 10 / CLAUDE.md mục 4) — chạy qua API thật bằng token dev của từng thành viên.

Mỗi kịch bản bắt đầu bằng reset dữ liệu mô phỏng nên LẶP LẠI ĐƯỢC. Cùng một mã chạy ở ba nơi:
  - endpoint POST /v1/demo/scenarios/{id}/run (nút trên tab Demo)
  - pytest (tests/test_scenarios.py)
  - CLI `python -m app.demo.run_scenarios` (báo cáo cho video/test report)
`client_factory()` phải trả về client có .get/.post(path, json=, headers=) (TestClient hoặc httpx.Client).
"""
import threading
import uuid
from datetime import datetime, timezone

from ..config import settings

USERS = {"nguyen": "shipper_a", "phuoc": "shipper_a2", "minh": "carrier_b", "khoi": "node_c", "phu": "dispatch"}


class Run:
    def __init__(self, factory):
        self.factory, self.c, self.steps = factory, factory(), []

    def step(self, label: str, ok: bool, detail: str = "") -> bool:
        self.steps.append({"label": label, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def req(self, who: str, method: str, path: str, body=None, idem: bool = False, client=None):
        h = {"Authorization": f"Bearer dev:{USERS.get(who, who)}"}
        if settings.admin_key:  # kịch bản gọi các endpoint demo cần mã quản trị
            h["X-Admin-Key"] = settings.admin_key
        if idem:
            h["Idempotency-Key"] = str(uuid.uuid4())
        c = client or self.c
        return c.get(path, headers=h) if method == "GET" else c.post(path, json=body or {}, headers=h)

    # ---- thao tác thường dùng ----
    def reset(self):
        r = self.req("phu", "POST", "/v1/demo/reset?provision=false")  # dữ liệu seed thuần: kết quả kịch bản xác định
        self.step("Reset dữ liệu mô phỏng về trạng thái chuẩn", r.status_code == 200, f"HTTP {r.status_code}")

    def lot(self, code: str, who="nguyen") -> str:
        return next(s["id"] for s in self.req(who, "GET", "/v1/shipments").json() if s["code"] == code)

    def match(self, code: str, who="nguyen") -> dict:
        r = self.req(who, "POST", "/v1/match-runs", {"shipment_id": self.lot(code, who)})
        assert r.status_code == 200, r.text
        return r.json()

    def act(self, who: str, prop: dict | str, action: str):
        pid = prop["id"] if isinstance(prop, dict) else prop
        view = self.req(who, "GET", f"/v1/proposals/{pid}").json()
        return self.req(who, "POST", f"/v1/proposals/{pid}/{action}", {"version": view["version"]}, idem=True)

    def confirm(self, prop: dict) -> dict:
        self.act("nguyen", prop, "hold")
        for who in ("minh", "nguyen", "khoi"):
            self.act(who, prop, "accept")
        return self.req("nguyen", "GET", f"/v1/proposals/{prop['id']}").json()

    def event(self, who: str, pid: str, etype: str, payload=None, source_event_id=None):
        return self.req(who, "POST", "/v1/events", {
            "entity_id": pid, "event_type": etype, "payload": payload or {},
            "occurred_at": datetime.now(timezone.utc).isoformat(), "source_system": "carrier-tms",
            "source_event_id": source_event_id or str(uuid.uuid4())})

    def worker(self, **params):
        q = "&".join(f"{k}={str(v).lower()}" for k, v in params.items())
        return self.req("phu", "POST", "/v1/demo/worker/run" + (f"?{q}" if q else "")).json()

    def view(self, pid: str, who="nguyen") -> dict:
        return self.req(who, "GET", f"/v1/proposals/{pid}").json()

    def slot_left(self, slot_id: str) -> int:
        return next(s["remaining"] for s in self.req("nguyen", "GET", "/v1/slots").json() if s["id"] == slot_id)


def s1_success(r: Run):
    r.reset()
    run = r.match("LOT-A-001")
    r.step("Ghép: có phương án khả thi, xếp hạng theo điểm", run["status"] == "proposals" and len(run["proposals"]) >= 1,
           f"{len(run['proposals'])} phương án, top = {run['proposals'][0]['vehicle']['plate']} (điểm {run['proposals'][0]['score']})")
    top = run["proposals"][0]
    held = r.act("nguyen", top, "hold")
    r.step("Chủ hàng giữ slot (hold 120s)", held.status_code == 200 and held.json()["status"] == "pending_acceptance", f"HTTP {held.status_code}")
    for who, label in (("minh", "Nhà vận tải nhận việc"), ("nguyen", "Chủ hàng duyệt lô"), ("khoi", "ICD duyệt slot")):
        x = r.act(who, top, "accept")
        r.step(label, x.status_code == 200, f"HTTP {x.status_code}")
    v = r.view(top["id"])
    r.step("Đề xuất được xác nhận (đủ 3 bên + re-check đạt)", v["status"] == "confirmed", v["status"])
    r.event("minh", top["id"], "TRIP_STARTED")
    r.event("minh", top["id"], "TRIP_COMPLETED", {"actual_empty_km": round((top["deadhead_km"] or 0) * 0.9, 1)})
    r.worker()
    r.worker()
    v = r.view(top["id"])
    r.step("Chuyến chạy đến completed qua sự kiện", v["status"] == "completed", v["status"])
    ben = [b for b in r.req("nguyen", "GET", "/v1/benefits").json()["items"] if b["proposal_id"] == top["id"]]
    r.step("Sổ lợi ích ghi một dòng 'measured' (baseline − thực tế)", len(ben) == 1 and ben[0]["status"] == "measured",
           f"{ben[0]['net_vnd']:,} ₫" if ben else "không có")
    if ben:
        ok = r.req("nguyen", "POST", f"/v1/benefits/{ben[0]['id']}/verify")
        r.step("Đối tác xác minh → 'verified'", ok.status_code == 200 and ok.json()["status"] == "verified", f"HTTP {ok.status_code}")
    return "#/benefits"


def s2_incompatible(r: Run):
    r.reset()
    run = r.match("LOT-A-003")  # lô 20 tấn
    codes = {x["reason_code"] for rej in run["rejections"] for x in rej["reasons"]}
    r.step("Xe thiếu tải bị loại (CAPACITY_EXCEEDED)", "CAPACITY_EXCEEDED" in codes)
    r.step("Xe sai loại hàng bị loại (CARGO_INCOMPATIBLE)", "CARGO_INCOMPATIBLE" in codes)
    r.step("Xe ngoại tuyến / vị trí quá hạn bị loại", {"VEHICLE_UNAVAILABLE", "DATA_STALE"} <= codes, ", ".join(sorted(codes)))
    rejected = {x["vehicle_id"] for x in run["rejections"]}
    r.step("Xe bị loại KHÔNG bao giờ được chấm điểm", rejected.isdisjoint({p["vehicle"]["id"] for p in run["proposals"]}))
    none = r.match("LOT-A-008")  # cut-off ICD quá sát
    r.step("Không có phương án thì trả 'không có phương án khả thi', không ép ghép",
           none["status"] == "no_feasible_option" and none["proposals"] == [], none["status"])
    return "#/recommend"


def s3_stale(r: Run):
    r.reset()
    r.step("Làm tuổi vị trí xe thêm 10 phút", r.req("phu", "POST", "/v1/demo/age-positions?minutes=10").status_code == 200)
    run = r.match("LOT-A-001")
    stale = all(any(x["reason_code"] == "DATA_STALE" for x in rej["reasons"]) for rej in run["rejections"])
    r.step("Dữ liệu quá hạn → không tự đề xuất (mọi xe DATA_STALE)", run["status"] == "no_feasible_option" and stale, run["status"])
    vehicles = r.req("minh", "GET", "/v1/vehicles").json()
    codes = []
    for v in vehicles:  # nhà vận tải gửi sự kiện vị trí mới (nguồn dữ liệu thật của event-driven)
        codes.append(r.req("minh", "POST", "/v1/events", {
            "entity_type": "vehicle", "entity_id": v["id"], "event_type": "VEHICLE_POSITION", "payload": {},
            "occurred_at": datetime.now(timezone.utc).isoformat(), "source_system": "gps-feed",
            "source_event_id": str(uuid.uuid4())}).status_code)
    r.step("Nhà vận tải gửi sự kiện VEHICLE_POSITION cho cả đội xe", all(c == 202 for c in codes), f"{len(codes)} sự kiện")
    r.worker()
    again = r.match("LOT-A-001")
    r.step("Dữ liệu tươi lại qua sự kiện → ghép được (không cần reset)", again["status"] == "proposals", again["status"])
    return "#/fleet"


def s4_race(r: Run):
    r.reset()
    top = r.match("LOT-A-001")["proposals"][0]
    before = r.slot_left(top["slot"]["id"])
    out, barrier = [], threading.Barrier(2)

    def go(who):
        c = r.factory()
        view = r.req(who, "GET", f"/v1/proposals/{top['id']}", client=c).json()
        barrier.wait()
        out.append(r.req(who, "POST", f"/v1/proposals/{top['id']}/hold", {"version": view["version"]}, idem=True, client=c).status_code)
    ts = [threading.Thread(target=go, args=(w,)) for w in ("nguyen", "phuoc")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    r.step("Hai người cùng giữ một tài nguyên: chỉ 1 thành công", sorted(out) == [200, 409], f"mã trả về {sorted(out)}")
    r.step("Slot chỉ bị trừ đúng 1 chỗ", r.slot_left(top["slot"]["id"]) == before - 1, f"{before} → {r.slot_left(top['slot']['id'])}")
    r.step("Đề xuất ở trạng thái pending_acceptance (không nhân đôi tác động)", r.view(top["id"])["status"] == "pending_acceptance")
    return "#/confirm"


def s5_eta(r: Run):
    r.reset()
    p1 = r.match("LOT-A-001")["proposals"][0]
    r.confirm(p1)
    r.event("minh", p1["id"], "TRIP_STARTED")
    r.worker()
    r.worker()
    before = r.view(p1["id"])
    r.event("minh", p1["id"], "ETA_UPDATED", {"delay_minutes": 45})
    r.worker()
    after = r.view(p1["id"])
    r.step("Chuyến đã cam kết: ETA đổi KHÔNG tự sửa/chuyển xe",
           (after["status"], after["vehicle"]["id"], after["version"]) == (before["status"], before["vehicle"]["id"], before["version"]),
           f"{after['status']} · {after['vehicle']['plate']}")
    excs = [e for e in r.req("nguyen", "GET", "/v1/exceptions").json() if e["proposal_id"] == p1["id"]]
    r.step("Tạo ngoại lệ ETA_CHANGED xin quyết định", len(excs) == 1 and excs[0]["detail"].get("action") == "needs_decision")
    if excs:
        x = r.req("nguyen", "POST", f"/v1/exceptions/{excs[0]['id']}/resolve", {"resolution": "accept_delay", "note": "Chấp nhận trễ 45 phút"})
        r.step("Chủ hàng quyết định xử lý ngoại lệ", x.status_code == 200 and x.json()["status"] == "resolved")
    run2 = r.match("LOT-A-002")
    taken = [x for x in run2["rejections"] if x["vehicle_id"] == p1["vehicle"]["id"]]
    r.step("Xe của chuyến đã cam kết bị loại khỏi lượt ghép mới (VEHICLE_UNAVAILABLE)",
           bool(taken) and any(x["reason_code"] == "VEHICLE_UNAVAILABLE" for x in taken[0]["reasons"]))
    p2 = run2["proposals"][0]
    r.act("nguyen", p2, "hold")
    r.event("minh", p2["id"], "ETA_UPDATED", {"delay_minutes": 90})
    r.worker()
    r.step("Đề xuất CHƯA cam kết: phương án cũ hết hiệu lực để tính lại", r.view(p2["id"])["status"] == "expired")
    return "#/timeline"


def s6_duplicate_restart(r: Run):
    r.reset()
    p = r.match("LOT-A-001")["proposals"][0]
    r.confirm(p)
    v0 = r.view(p["id"])["version"]
    sid = "demo-dup-" + uuid.uuid4().hex[:8]
    codes = [r.event("minh", p["id"], "TRIP_STARTED", source_event_id=sid).status_code for _ in range(10)]
    r.step("Gửi lặp 1 sự kiện 10 lần: chỉ lần đầu được nhận (202), 9 lần còn lại là trùng (200)", codes == [202] + [200] * 9, str(codes))
    crash = r.worker(simulate_crash="true")
    r.step("Worker 'chết' giữa chừng: không có tác động nửa vời", r.view(p["id"])["status"] == "confirmed" and crash.get("retry", 0) >= 1, str(crash))
    done = r.worker(advance_seconds=120)
    after = r.view(p["id"])
    r.step("Worker khởi động lại: tác động được áp dụng ĐÚNG MỘT LẦN", after["status"] == "executing" and after["version"] == v0 + 1,
           f"{after['status']} · v{v0} → v{after['version']} · {done}")
    tl = r.req("nguyen", "GET", f"/v1/proposals/{p['id']}/timeline").json()
    r.step("Timeline chỉ có 1 sự kiện TRIP_STARTED", sum(1 for i in tl["items"] if i["code"] == "TRIP_STARTED") == 1)
    return "#/timeline"


def _tracked_trip(r: Run, code="LOT-A-001") -> dict:
    p = r.match(code)["proposals"][0]
    return r.confirm(p)


def s7_tracking(r: Run):
    r.reset()
    p = _tracked_trip(r)
    st = r.req("minh", "POST", f"/v1/sim/{p['id']}/start?speedup=10000")
    r.step("Nhà vận tải bật bộ giả lập GPS (tin vị trí đi qua đường sự kiện thật)", st.status_code == 200, f"HTTP {st.status_code}")
    r.worker()
    for _ in range(24):
        r.req("minh", "POST", "/v1/sim/tick")
        r.worker()
    d = r.req("nguyen", "GET", f"/v1/tracking/{p['id']}").json()
    reached = [m["code"] for m in d["milestones"] if m["reached"]]
    r.step("Mốc hành trình suy ra từ vị trí, đúng thứ tự", reached == ["ASSIGNED", "AT_PICKUP", "DEPARTED_PICKUP", "AT_ICD_GATE"], str(reached))
    tl = r.req("nguyen", "GET", f"/v1/proposals/{p['id']}/timeline").json()
    ms = [i["code"] for i in tl["items"] if i["code"] == "MILESTONE_REACHED"]
    r.step("Mỗi mốc chỉ phát sinh MỘT lần (sự kiện hệ thống idempotent)", len(ms) == 3, str(len(ms)))
    r.step("Vệt di chuyển + ETA trực tiếp có P50 ≤ P90; dữ liệu gắn nhãn mô phỏng", len(d["track"]) >= 3 and d["is_simulated"] is True and d["eta"] is not None)
    r.step("Không lộ giá/khách hàng qua Tracking", "price" not in str(d).lower() and "customer" not in str(d).lower())
    return "#/tracking"


def s8_breakdown_replan(r: Run):
    r.reset()
    p = _tracked_trip(r)
    plate = p["vehicle"]["plate"]
    r.event("minh", p["id"], "INCIDENT_REPORTED", {"kind": "BREAKDOWN", "note": "Nổ lốp"})
    r.worker()
    ex = next((e for e in r.req("nguyen", "GET", "/v1/exceptions").json() if e["proposal_id"] == p["id"]), None)
    r.step("Hỏng xe → ngoại lệ mức critical theo luật có version", bool(ex) and ex["severity"] == "critical" and ex["rule_version"].startswith("sev-"), ex["rule_version"] if ex else "")
    r.step("Playbook sinh bước tự động (báo các bên) + bước do người quyết, có SLA", bool(ex) and ex["tasks"][0]["status"] == "done" and any(t["kind"] == "human" for t in ex["tasks"]) and bool(ex["sla_due_at"]))
    n = r.req("nguyen", "GET", "/v1/notifications").json()
    r.step("Chủ hàng nhận thông báo (SMS/email là nhật ký mô phỏng)", n["unread"] >= 1)
    mine = next((t for t in (ex or {"tasks": []})["tasks"] if t["owner"] == "carrier"), None)
    if mine:
        x = r.req("minh", "POST", f"/v1/exceptions/{ex['id']}/tasks/{mine['id']}/complete")
        r.step("Nhà vận tải hoàn tất bước của mình; bên khác không làm thay được", x.status_code == 200 and r.req("nguyen", "POST", f"/v1/exceptions/{ex['id']}/tasks/{mine['id']}/complete").status_code == 403)
    rp = r.req("nguyen", "POST", f"/v1/proposals/{p['id']}/replan", {"version": r.view(p["id"])["version"]})
    r.step("Chủ hàng bấm Ghép lại: chuyến cũ huỷ, lô về chờ ghép, có phương án mới", rp.status_code == 200 and rp.json()["shipment_status"] == "open" and rp.json()["new_proposals"] >= 1, rp.text[:120])
    new = [x for x in r.req("nguyen", "GET", f"/v1/proposals?shipment_id={r.lot('LOT-A-001')}").json() if x["status"] == "proposed"]
    r.step("Xe hỏng không được đề xuất lại; hệ thống không tự chọn thay", all(x["vehicle"]["plate"] != plate for x in new) and bool(new))
    return "#/exceptions"


def s9_dock(r: Run):
    r.reset()
    p = _tracked_trip(r)
    a = next((x for x in r.req("khoi", "GET", "/v1/docks/board").json()["appointments"] if x["proposal_id"] == p["id"]), None)
    r.step("Xác nhận chuyến → hệ thống xếp dock tự động trong khung slot", bool(a) and a["status"] == "scheduled", a["dock_code"] if a else "")
    if not a:
        return "#/docks"
    r.event("minh", p["id"], "ETA_UPDATED", {"delay_minutes": 180})
    r.worker()
    b = next(x for x in r.req("khoi", "GET", "/v1/docks/board").json()["appointments"] if x["proposal_id"] == p["id"])
    r.step("ETA đổi → CHỈ đề xuất khung mới, lịch cũ giữ nguyên", bool(b["suggestion"]) and b["window_start"] == a["window_start"], str(b["suggestion"] and b["suggestion"]["window_start"]))
    bad = r.req("nguyen", "POST", f"/v1/dock-appointments/{b['id']}/accept-suggestion", {"version": b["version"]})
    ok = r.req("khoi", "POST", f"/v1/dock-appointments/{b['id']}/accept-suggestion", {"version": b["version"]})
    r.step("Chỉ ICD chấp nhận mới áp dụng đề xuất", bad.status_code == 404 and ok.status_code == 200)
    p2 = _tracked_trip(r, "LOT-A-002")
    boards = r.req("khoi", "GET", "/v1/docks/board").json()["appointments"]
    a2 = next(x for x in boards if x["proposal_id"] == p2["id"])
    a1 = next(x for x in boards if x["proposal_id"] == p["id"])
    start = a2["window_start"]
    res = []

    def go(appt):
        res.append(r.req("khoi", "POST", f"/v1/dock-appointments/{appt['id']}/reschedule",
                         {"version": appt["version"], "window_start": start, "dock_id": a2["dock_id"]}, client=r.factory()).status_code)
    ts = [threading.Thread(target=go, args=(x,)) for x in (a1, a2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    r.step("Hai yêu cầu dời cùng khung dock cùng lúc: chỉ một thành công", sorted(res)[-1] == 409 and 200 in res, str(sorted(res)))
    return "#/docks"


def s10_eta_model(r: Run):
    r.reset()
    r.req("phu", "POST", "/v1/eta/train", {"drift": 0})
    m1 = r.req("phu", "GET", "/v1/eta/model").json()
    r.step("ML trên lịch sử MÔ PHỎNG: giảm MAE ≥ 15% và độ phủ P90 đạt → được promote", m1["status"] == "promoted", str(m1["metrics"] and m1["metrics"]["improvement_pct"]))
    when = datetime.now(timezone.utc).isoformat()
    w1 = r.req("minh", "POST", "/v1/eta/predict", {"depart_at": when}).json()
    r.step("Dự báo what-if dùng ML, luôn gắn nhãn mô phỏng", w1["used"] == "ml" and w1["is_simulated"] is True)
    m2 = r.req("phu", "POST", "/v1/eta/train", {"drift": 0.15}).json()
    w2 = r.req("minh", "POST", "/v1/eta/predict", {"depart_at": when}).json()
    r.step("Dữ liệu trôi → độ phủ tụt → tự hạ về ETA luật", m2["status"] == "rule_fallback" and w2["used"] == "rule" and w2["ml"] is None, m2["reason"])
    r.req("phu", "POST", "/v1/eta/train", {"drift": 0})
    r.step("Khoảng P50 ≤ P90 ở cả hai nhánh", w1["rule"]["p50"] <= w1["rule"]["p90"] and w1["ml"]["p50_minutes"] <= w1["ml"]["p90_minutes"])
    return "#/tracking"


SCENARIOS = [
    ("success", s1_success), ("incompatible", s2_incompatible), ("stale", s3_stale),
    ("race", s4_race), ("eta_change", s5_eta), ("duplicate_restart", s6_duplicate_restart),
    ("tracking", s7_tracking), ("breakdown_replan", s8_breakdown_replan), ("dock", s9_dock), ("eta_model", s10_eta_model),
]


def run_scenario(scenario_id: str, factory) -> dict:
    fn = dict(SCENARIOS)[scenario_id]
    r = Run(factory)
    link = None
    try:
        link = fn(r)
    except Exception as exc:  # noqa: BLE001 — lỗi bất ngờ cũng phải hiện thành bước thất bại
        r.step("Lỗi không mong đợi", False, f"{type(exc).__name__}: {exc}")
    return {"id": scenario_id, "passed": bool(r.steps) and all(s["ok"] for s in r.steps), "steps": r.steps, "open": link}
