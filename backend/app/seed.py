"""Seed dữ liệu MÔ PHỎNG cho prototype (DRAFT 3.1): 3 tổ chức, 4 vai trò, 10 xe, 20 lô, 20 slot.

Chạy:
  python -m app.seed            # reset toàn bộ rồi seed lại (thời gian tương đối theo "bây giờ")
  python -m app.seed --retime   # giữ dữ liệu, chỉ dịch mốc thời gian theo "bây giờ" (đưa demo về trạng thái tươi)
Mọi bản ghi is_simulated=True. Có chủ ý một số ca để demo hard gate (xe thiếu tải, sai loại hàng,
trễ giờ, vị trí xe quá hạn, lô thiếu trọng lượng, slot đầy).
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import fleet, models as m
from .config import settings
from .db import SessionLocal, engine

NS = uuid.UUID("6f1c6c1e-0000-4000-8000-00000000a001")


def uid(name: str) -> uuid.UUID:
    return uuid.uuid5(NS, name)


ASSUMPTIONS_V1 = {
    "rule_version": "rules-v1",
    "stale_position_minutes": 5,  # DRAFT 5.1: ngưỡng pilot, cấu hình — không phải chuẩn chung
    "stale_shipment_minutes": 60,  # tuổi tối đa của dữ liệu lô (SLA riêng cho sự kiện nghiệp vụ)
    "max_proposals": 3,
    "hold_seconds": 120,
    "deadhead_minutes": 25,  # thời gian xe tới điểm lấy (ETA luật, rule-based)
    "transit_minutes": 90,  # điểm lấy → ICD (bảng tuyến–khung giờ, rule-based)
    "handling_minutes": 20,
    "eta_method": "rule-based",
    # ETA luật (assume-v2): P50 = bảng tuyến (deadhead + transit); khung giờ chỉ nới độ bất định P90. Tham số MÔ PHỎNG.
    "eta": {"model_version": "eta-rule-v1", "p90_buffer_minutes": 10, "peak_am_hours": [7, 8], "peak_pm_hours": [16, 17, 18],
            "night_hours": [22, 23, 0, 1, 2, 3, 4, 5], "tz_offset_hours": 7,
            "spread": {"normal": 0.15, "peak_am": 0.35, "peak_pm": 0.45, "night": 0.10},
            "live_speed_kmh_fallback": 35.0, "live_p90_speed_factor": 0.75},
    "score_weights": {"fit": 0.4, "time_margin": 0.3, "empty_km_saved": 0.3},  # tổng = 1
    "cost_per_km_vnd": 14000,
    "empty_km_baseline": 38,
}

TABLES = [
    "notifications", "dock_appointments", "exception_tasks", "outbox_jobs", "trip_tracks", "trip_routes", "sim_trips", "benefit_ledger", "exceptions", "decisions", "reservations", "proposals",
    "assumption_sets", "external_id_map", "events", "docks", "slots", "availability_windows", "vehicles",
    "shipment_participants", "logistics_units", "shipment_legs", "shipments", "locations",
    "memberships", "users", "organizations",
]


def reset(session: Session, keep_registered: bool = False) -> None:
    if settings.data_mode != "mock":  # chốt chặn: không bao giờ TRUNCATE khi không phải môi trường mô phỏng
        raise RuntimeError("Refusing to reset: PIVOT_DATA_MODE is not 'mock'")
    # DELETE theo thứ tự khoá ngoại (con trước cha) thay vì TRUNCATE: TRUNCATE cần khoá độc quyền trên mọi bảng nên
    # bế tắc (deadlock) với worker nền / request đang chạy song song. DELETE chỉ khoá theo dòng, tương thích MVCC.
    for table in TABLES:
        if not keep_registered:
            session.execute(text(f"DELETE FROM {table}"))
        elif table == "memberships":  # giữ người dùng/tổ chức tự đăng nhập (is_registered) — chỉ xoá dữ liệu mẫu của seed
            session.execute(text("DELETE FROM memberships WHERE user_id IN (SELECT id FROM users WHERE NOT is_registered)"))
        elif table in ("users", "organizations"):
            session.execute(text(f"DELETE FROM {table} WHERE NOT is_registered"))
        else:
            session.execute(text(f"DELETE FROM {table}"))


def reset_and_seed(session: Session, now: datetime | None = None, keep_registered: bool = True, provision: bool = True) -> dict:
    """Reset dữ liệu mô phỏng về trạng thái chuẩn: giữ danh tính người đã đăng nhập và cấp lại dữ liệu mẫu cho họ."""
    from .accounts import provision_registered

    reset(session, keep_registered=keep_registered)
    info = seed(session, now)
    info["registered_orgs_reprovisioned"] = provision_registered(session, now) if (keep_registered and provision) else 0
    return info


def seed(session: Session, now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    H = lambda h: now + timedelta(hours=h)  # noqa: E731
    Mi = lambda mi: now + timedelta(minutes=mi)  # noqa: E731

    # --- tổ chức + người dùng + vai trò (ba tổ chức, bốn vai trò) ---
    orgs = {
        "A": m.Organization(id=uid("org-A"), name="Công ty Hàng hóa A (Shipper)", org_type="shipper"),
        "B": m.Organization(id=uid("org-B"), name="Vận tải B (Carrier)", org_type="carrier"),
        "C": m.Organization(id=uid("org-C"), name="ICD Cảng C (Node)", org_type="node"),
    }
    session.add_all(orgs.values())
    users = {
        "shipper_a": ("A", "shipper", "Nguyên"),
        "shipper_a2": ("A", "shipper", "Phước"),  # cùng tổ chức A: test chia sẻ trong tổ chức
        "carrier_b": ("B", "carrier", "Minh"),
        "node_c": ("C", "node_operator", "Khôi"),
        "dispatch": ("C", "dispatcher", "Phú"),
    }
    for key, (_, _, name) in users.items():
        session.add(m.User(id=uid("user-" + key), email=f"{key}@demo.local", name=name))
    session.flush()  # không có relationship() → tự flush theo thứ tự phụ thuộc FK
    for key, (org, role, _) in users.items():
        session.add(m.Membership(id=uid("mem-" + key), user_id=uid("user-" + key),
                                 org_id=orgs[org].id, role=role))
    session.flush()

    # --- địa điểm: một hành lang KCN–ICD ---
    locs = {
        "kcn1": m.Location(id=uid("loc-kcn1"), name="KCN Sóng Thần (mô phỏng)", kind="industrial_zone", lat=10.9, lng=106.74),
        "kcn2": m.Location(id=uid("loc-kcn2"), name="KCN VSIP I (mô phỏng)", kind="industrial_zone", lat=10.92, lng=106.72),
        "icd": m.Location(id=uid("loc-icd"), name="ICD Cảng C (mô phỏng)", kind="icd", lat=10.85, lng=106.8),
        "depot": m.Location(id=uid("loc-depot"), name="Depot Thủ Đức (mô phỏng)", kind="depot", lat=10.87, lng=106.77),
    }
    session.add_all(locs.values())
    session.flush()
    fleet.ensure_yards(session)  # thêm các bãi đậu (kind="yard") — xe của người tự đăng ký được rải lên đó; 10 xe seed của B vẫn ở depot
    session.add(m.AssumptionSet(id=uid("assume-v2"), version="assume-v2",
                                params=ASSUMPTIONS_V1 | {"anchor_at": now.isoformat()}))
    session.flush()

    # --- 10 xe (carrier B). Có ca cố ý: thiếu tải, chỉ chở lạnh, trễ giờ, vị trí quá hạn, offline ---
    #        (plate, cargo_types, kg, m3, status, pos_age_min, free_from_h, location)
    vspec = [
        ("51C-100.01", ["dry"], 24000, 60, "available", 1, 0.0, "depot"),
        ("51C-100.02", ["dry"], 24000, 60, "available", 2, 0.5, "depot"),
        ("51C-100.03", ["dry"], 18000, 45, "available", 1, 0.0, "kcn1"),
        ("51C-100.04", ["dry"], 18000, 45, "available", 3, 1.0, "kcn2"),
        ("51C-100.05", ["dry"], 8000, 25, "available", 2, 0.0, "kcn1"),   # thiếu tải với lô lớn
        ("51C-100.06", ["dry"], 8000, 25, "available", 1, 0.5, "kcn2"),
        ("51C-100.07", ["cold"], 15000, 40, "available", 2, 0.0, "depot"),  # xe lạnh: sai loại hàng với hàng khô
        ("51C-100.08", ["dry"], 24000, 60, "available", 22, 0.0, "depot"),  # vị trí quá hạn → DATA_STALE
        ("51C-100.09", ["dry"], 18000, 45, "available", 2, 7.0, "kcn1"),    # rảnh quá muộn → trễ giờ lấy hàng
        ("51C-100.10", ["dry"], 24000, 60, "offline", 4, 0.0, "depot"),     # VEHICLE_UNAVAILABLE
    ]
    vehicles = []
    for i, (plate, cargo, kg, m3, status, age, free_h, loc) in enumerate(vspec, 1):
        v = m.Vehicle(id=uid(f"veh-{i}"), tenant_id=orgs["B"].id, plate=plate, cargo_types=cargo,
                      capacity_kg=kg, capacity_m3=m3, status=status, position_updated_at=Mi(-age))
        vehicles.append(v)
        session.add(v)
    session.flush()
    for i, (_, _, _, _, _, _, free_h, loc) in enumerate(vspec, 1):
        session.add(m.AvailabilityWindow(id=uid(f"win-{i}"), vehicle_id=uid(f"veh-{i}"),
                                         location_id=locs[loc].id, free_from=H(free_h), free_to=H(free_h + 9)))

    for code in ("D1", "D2"):  # dock của ICD (mô phỏng): lịch hẹn xe đặt theo dock
        session.add(m.Dock(id=uid(f"dock-{code}"), node_org_id=orgs["C"].id, location_id=locs["icd"].id, code=code, handling_minutes=30))
    # --- 20 slot ICD (node C) — slot mô phỏng, nguồn xác nhận = mock ---
    for i in range(1, 21):
        start = H(2 + (i - 1) * 0.5)
        cap = 2 + (i % 3)
        remaining = 0 if i in (3, 7) else cap  # SLOT_FULL
        session.add(m.Slot(id=uid(f"slot-{i}"), node_org_id=orgs["C"].id, location_id=locs["icd"].id,
                           start_at=start, end_at=start + timedelta(minutes=30), capacity=cap,
                           remaining=remaining, source="mock"))

    # --- 20 lô: 10 của A (shipper), 10 của B (forwarder/carrier). Tách riêng để test cô lập A/B ---
    #        (owner, cargo, kg, m3, ready_h, deadline_h, cutoff_h, origin)
    big = 20000
    lspec = [
        ("A", "dry", 12000, 30, 1, 4, 12, "kcn1"),
        ("A", "dry", 9000, 24, 1, 4, 12, "kcn2"),
        ("A", "dry", big, 50, 1, 5, 12, "kcn1"),      # lô lớn: loại xe 8t
        ("A", "dry", 15000, 40, 2, 5, 12, "kcn2"),
        ("A", "cold", 6000, 18, 1, 4, 12, "kcn1"),    # hàng lạnh: xe khô bị loại
        ("A", "dry", 7000, 20, 1, 1.2, 12, "kcn2"),   # deadline gấp → chỉ xe rảnh sớm đạt
        ("A", "dry", None, None, 2, 5, 12, "kcn1"),   # thiếu trọng lượng → UNKNOWN, cần bổ sung dữ liệu
        ("A", "dry", 5000, 14, 2, 6, 3.0, "kcn2"),    # cutoff ICD sát → CUTOFF_RISK
        ("A", "dry", 11000, 28, 3, 6, 14, "kcn1"),
        ("A", "dry", 13000, 33, 3, 7, 14, "kcn2"),
        ("B", "dry", 10000, 26, 1, 4, 12, "kcn1"),
        ("B", "dry", 16000, 42, 1, 4, 12, "kcn2"),
        ("B", "dry", 6000, 16, 2, 5, 12, "kcn1"),
        ("B", "dry", 19000, 48, 2, 5, 12, "kcn2"),
        ("B", "cold", 8000, 22, 1, 4, 12, "kcn1"),
        ("B", "dry", 14000, 36, 3, 6, 14, "kcn2"),
        ("B", "dry", 9500, 25, 3, 6, 14, "kcn1"),
        ("B", "dry", 12500, 31, 3, 7, 14, "kcn2"),
        ("B", "dry", 7500, 19, 4, 8, 15, "kcn1"),
        ("B", "dry", 17000, 44, 4, 8, 15, "kcn2"),
    ]
    customers = ["Khách hàng mô phỏng 01", "Khách hàng mô phỏng 02", "Khách hàng mô phỏng 03"]
    for i, (owner, cargo, kg, m3, ready, dl, cut, origin) in enumerate(lspec, 1):
        sid = uid(f"ship-{i}")
        session.add(m.Shipment(
            id=sid, tenant_id=orgs[owner].id, code=f"LOT-{owner}-{i:03d}", cargo_type=cargo,
            weight_kg=kg, volume_m3=m3, origin_location_id=locs[origin].id, dest_location_id=locs["icd"].id,
            ready_at=H(ready), pickup_deadline=H(dl), cutoff_at=H(cut), status="open",
            price_vnd=(None if kg is None else int(kg * 160)), customer_name=customers[i % 3],
            data_updated_at=Mi(-3),
        ))
        session.flush()
        session.add(m.ShipmentLeg(id=uid(f"leg-{i}"), shipment_id=sid, seq=1,
                                  from_location_id=locs[origin].id, to_location_id=locs["icd"].id))
        session.flush()
        session.add(m.LogisticsUnit(id=uid(f"lu-{i}"), shipment_id=sid, leg_id=uid(f"leg-{i}"),
                                    sscc=f"SIM{i:014d}", weight_kg=kg))
        # Chủ lô là participant. Node/đối tác khác chỉ được thêm làm participant khi có đề xuất
        # liên quan (không chia sẻ lô mặc định — "đủ dùng", DRAFT mục 12).
        session.add(m.ShipmentParticipant(id=uid(f"part-own-{i}"), shipment_id=sid,
                                          org_id=orgs[owner].id, role="shipper", can_see_price=True))
    session.flush()
    return {"organizations": 3, "users": 5, "vehicles": 10, "shipments": 20, "slots": 20, "now": now.isoformat()}


def retime(session: Session, now: datetime | None = None) -> timedelta:
    """Dịch mọi mốc thời gian của dữ liệu seed theo "bây giờ" mà KHÔNG xoá đề xuất/sự kiện/quyết định.

    Giữ nguyên tuổi tương đối (xe quá hạn vẫn quá hạn, lô gấp vẫn gấp) nên 6 kịch bản demo lặp lại được.
    Chỉ chạy được với dữ liệu mô phỏng (data_mode = mock).
    """
    if settings.data_mode != "mock":
        raise RuntimeError("Refusing to retime: PIVOT_DATA_MODE is not 'mock'")
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    from .booking.service import reset_open_commitments

    aset = session.query(m.AssumptionSet).filter_by(is_active=True).one()
    anchor = aset.params.get("anchor_at")
    delta = now - datetime.fromisoformat(anchor) if anchor else timedelta(0)  # thiếu anchor → chỉ ghi anchor mới
    reset_open_commitments(session, now)  # hold/đề xuất đang mở được expire thay vì lệch thời gian
    from .accounts import registered_org_ids

    skip = registered_org_ids(session)  # dữ liệu của người tự đăng nhập tạo SAU mốc anchor → không dịch (tránh lệch mốc)
    veh_owner = {v.id: v.tenant_id for v in session.query(m.Vehicle).all()}
    owner_of = {
        m.Shipment: lambda r: r.tenant_id, m.Vehicle: lambda r: r.tenant_id,
        m.AvailabilityWindow: lambda r: veh_owner.get(r.vehicle_id), m.Slot: lambda r: r.node_org_id,
    }
    for model, cols in (
        (m.Shipment, ("ready_at", "pickup_deadline", "cutoff_at", "data_updated_at")),
        (m.Vehicle, ("position_updated_at",)),
        (m.AvailabilityWindow, ("free_from", "free_to")),
        (m.Slot, ("start_at", "end_at")),
    ):
        for row in session.query(model).all():
            if owner_of[model](row) in skip:
                continue
            for col in cols:
                value = getattr(row, col)
                if value is not None:
                    setattr(row, col, value + delta)
    for appt, dock in session.query(m.DockAppointment, m.Dock).join(m.Dock, m.Dock.id == m.DockAppointment.dock_id).all():
        if dock.node_org_id in skip:
            continue
        for col in ("window_start", "window_end", "base_eta_at", "eta_at", "suggested_start", "suggested_end"):
            value = getattr(appt, col)
            if value is not None:
                setattr(appt, col, value + delta)
    aset.params = {**aset.params, "anchor_at": now.isoformat()}  # gán lại để SQLAlchemy nhận ra JSON đổi
    return delta


def seed_if_empty(session: Session) -> dict | None:
    """Triển khai lần đầu: seed khi DB trống; các lần khởi động sau KHÔNG đụng vào dữ liệu người dùng đã nhập."""
    if session.query(m.Organization).count() > 0:
        return None
    return seed(session)


def main() -> None:
    import sys

    with SessionLocal() as session:
        if "--if-empty" in sys.argv:
            info = seed_if_empty(session)
            session.commit()
            print("Seed OK (DB trống → đã seed dữ liệu MÔ PHỎNG):" if info else "DB đã có dữ liệu → giữ nguyên.", info or "")
        elif "--retime" in sys.argv:
            delta = retime(session)
            session.commit()
            print(f"Retime OK: dịch mốc thời gian {delta} (dữ liệu MÔ PHỎNG).")
        else:
            info = reset_and_seed(session)
            session.commit()
            print("Seed OK (dữ liệu MÔ PHỎNG):", info)
    engine.dispose()


if __name__ == "__main__":
    main()
