"""Đăng nhập đơn giản cho demo: chỉ cần TÊN + VAI TRÒ (không mật khẩu).

- Danh tính = (tên đã chuẩn hoá, vai trò). Cùng cặp → cùng người/tổ chức; tên khác → tổ chức khác (đóng vai bên A, bên B…).
- Người mới có tổ chức RIÊNG + dữ liệu mẫu tự tạo theo vai trò (mọi bản ghi is_simulated=True).
- Năm cặp tên+vai trò của nhóm (Nguyên, Phước, Minh, Khôi, Phú) nối vào tài khoản mẫu A/B/C để kịch bản demo/test giữ nguyên.
- Token vẫn là `dev:<khoá>` nên mọi API/kiểm tra quyền không đổi. Không có mật khẩu → CHỈ dùng cho dữ liệu mô phỏng.
"""
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models as m
from .booking.service import BookingError

ROLES = ("shipper", "carrier", "node_operator", "dispatcher")
ORG_TYPE = {"shipper": "shipper", "carrier": "carrier", "node_operator": "node", "dispatcher": "platform"}
ROLE_SHORT = {"shipper": "shipper", "carrier": "carrier", "node_operator": "node", "dispatcher": "dispatch"}
ROLE_LABEL = {"shipper": "Chủ hàng", "carrier": "Nhà vận tải", "node_operator": "Điều hành ICD", "dispatcher": "Điều phối viên"}
MAX_REGISTERED_USERS = 500  # trần để bản công khai không bị tạo người dùng vô hạn
NAME_RE = re.compile(r"^[\w .'\-]{2,40}$", re.UNICODE)


def fold(text: str) -> str:
    """Bỏ dấu + hạ chữ thường (Hòa ≡ hoa)."""
    t = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


def normalize_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", (raw or "").strip())
    if not NAME_RE.match(name) or not re.search(r"[A-Za-z0-9]", fold(name)):
        raise BookingError("INVALID_NAME", "Name must be 2-40 characters: letters, digits, space, - . '", 422)
    return name


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")


# tên + vai trò của nhóm → khoá tài khoản mẫu hiện có
SEEDED_ALIASES = {
    ("nguyen", "shipper"): "shipper_a", ("phuoc", "shipper"): "shipper_a2", ("minh", "carrier"): "carrier_b",
    ("khoi", "node_operator"): "node_c", ("phu", "dispatcher"): "dispatch",
}


def account_key(name: str, role: str) -> str:
    return SEEDED_ALIASES.get((slug(name), role)) or f"{slug(name)}-{ROLE_SHORT[role]}"


# ---------------- dữ liệu mẫu cho tổ chức mới ----------------
def _locations(session: Session) -> dict:
    locs = list(session.execute(select(m.Location).order_by(m.Location.name)).scalars())
    return {"zones": [l for l in locs if l.kind == "industrial_zone"], "icd": next(l for l in locs if l.kind == "icd"),
            "depot": next((l for l in locs if l.kind == "depot"), None)}


def provision_org(session: Session, org: m.Organization, role: str, now: datetime | None = None) -> dict:
    """Cấp dữ liệu mẫu theo vai trò. Idempotent: tổ chức đã có dữ liệu loại đó thì bỏ qua."""
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    H = lambda h: now + timedelta(hours=h)  # noqa: E731
    L = _locations(session)
    made = {"shipments": 0, "vehicles": 0, "slots": 0}
    if role == "shipper" and not session.execute(select(m.Shipment.id).where(m.Shipment.tenant_id == org.id)).first():
        specs = [("dry", 12000, 30, 1, 4), ("dry", 8000, 20, 1, 4), ("dry", 19000, 48, 2, 5), ("cold", 6000, 18, 1, 4)]
        for i, (cargo, kg, m3, ready, dl) in enumerate(specs, 1):
            ship = m.Shipment(tenant_id=org.id, code=f"LOT-{i:03d}", cargo_type=cargo, weight_kg=kg, volume_m3=m3,
                              origin_location_id=L["zones"][i % len(L["zones"])].id, dest_location_id=L["icd"].id,
                              ready_at=H(ready), pickup_deadline=H(dl), cutoff_at=H(12), status="open",
                              price_vnd=int(kg * 160), customer_name=f"Khách mô phỏng {i}", data_updated_at=now - timedelta(minutes=3))
            session.add(ship)
            session.flush()
            session.add(m.ShipmentParticipant(shipment_id=ship.id, org_id=org.id, role="shipper", can_see_price=True))
            made["shipments"] += 1
    if role == "carrier" and not session.execute(select(m.Vehicle.id).where(m.Vehicle.tenant_id == org.id)).first():
        home = L["depot"] or L["zones"][0]
        for i, (kg, m3) in enumerate([(24000, 60), (18000, 45), (18000, 45), (8000, 25)], 1):
            plate = f"61{org.id.hex[0].upper()}-{org.id.hex[1:4]}.{i:02d}"
            veh = m.Vehicle(tenant_id=org.id, plate=plate, cargo_types=["dry"], capacity_kg=kg, capacity_m3=m3,
                            status="available", position_updated_at=now - timedelta(minutes=1))
            session.add(veh)
            session.flush()
            session.add(m.AvailabilityWindow(vehicle_id=veh.id, location_id=home.id, free_from=H(0.0), free_to=H(9)))
            made["vehicles"] += 1
    if role == "node_operator" and not session.execute(select(m.Slot.id).where(m.Slot.node_org_id == org.id)).first():
        for i in range(8):
            start = H(2 + i * 0.5)
            session.add(m.Slot(node_org_id=org.id, location_id=L["icd"].id, start_at=start, end_at=start + timedelta(minutes=30),
                               capacity=3, remaining=3, source="mock"))
            made["slots"] += 1
    if role == "node_operator" and not session.execute(select(m.Dock.id).where(m.Dock.node_org_id == org.id)).first():
        for code in ("D1", "D2"):
            session.add(m.Dock(node_org_id=org.id, location_id=L["icd"].id, code=code, handling_minutes=30))
    session.flush()
    return made


def provision_registered(session: Session, now: datetime | None = None) -> int:
    """Sau reset: cấp lại dữ liệu mẫu cho mọi tổ chức đã đăng ký."""
    rows = session.execute(select(m.Organization, m.Membership.role).join(m.Membership, m.Membership.org_id == m.Organization.id)
                           .where(m.Organization.is_registered.is_(True))).all()
    for org, role in rows:
        provision_org(session, org, role, now)
    return len(rows)


def registered_org_ids(session: Session) -> set[uuid.UUID]:
    return set(session.execute(select(m.Organization.id).where(m.Organization.is_registered.is_(True))).scalars())


# ---------------- đăng nhập ----------------
def login_or_register(session: Session, name: str, role: str) -> tuple[str, bool]:
    """Trả (khoá tài khoản, là_tài_khoản_mới). Khoá dùng làm token `dev:<khoá>`."""
    if role not in ROLES:
        raise BookingError("INVALID_ROLE", f"role must be one of {ROLES}", 422)
    name = normalize_name(name)
    key = account_key(name, role)
    email = f"{key}@demo.local"
    if session.execute(select(m.User.id).where(m.User.email == email)).first():
        return key, False
    if session.execute(select(func.count()).select_from(m.User).where(m.User.is_registered.is_(True))).scalar_one() >= MAX_REGISTERED_USERS:
        raise BookingError("REGISTRATION_LIMIT", "Too many registered demo users", 429)
    try:
        with session.begin_nested():
            org = m.Organization(name=f"{name} · {ROLE_LABEL[role]}", org_type=ORG_TYPE[role], is_registered=True)
            user = m.User(email=email, name=name, is_registered=True)
            session.add_all([org, user])
            session.flush()
            session.add(m.Membership(user_id=user.id, org_id=org.id, role=role))
            session.flush()
            provision_org(session, org, role)
    except IntegrityError:  # hai tab đăng nhập cùng một tên mới cùng lúc: người đến sau dùng tài khoản vừa tạo
        return key, False
    return key, True
