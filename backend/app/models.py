"""20 bảng tối thiểu theo DRAFT.md mục 4.2. Thời gian lưu UTC (timestamptz)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String,
    UniqueConstraint, Boolean, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)


def fk(target: str, nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target), nullable=nullable, index=True)


def ts(nullable: bool = False, default_now: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable, default=_now if default_now else None)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200))
    org_type: Mapped[str] = mapped_column(String(20))  # shipper | carrier | node | platform
    # tổ chức do người dùng tự đăng nhập tạo ra (khác dữ liệu seed): reset giữ lại, retime không dịch dữ liệu của họ
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", "role"),)
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = fk("users.id")
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    # shipper | carrier | node_operator | dispatcher
    role: Mapped[str] = mapped_column(String(20))


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))  # industrial_zone | icd | depot
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_shipment_tenant_code"),
        CheckConstraint("status IN ('open','matched','executing','completed','cancelled')",
                        name="ck_shipment_status"),
    )
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = fk("organizations.id")  # tổ chức sở hữu lô
    code: Mapped[str] = mapped_column(String(40))
    cargo_type: Mapped[str] = mapped_column(String(30))  # dry | cold | hazmat ...
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin_location_id: Mapped[uuid.UUID] = fk("locations.id")
    dest_location_id: Mapped[uuid.UUID] = fk("locations.id")
    ready_at: Mapped[datetime] = ts()
    pickup_deadline: Mapped[datetime | None] = ts(nullable=True)
    cutoff_at: Mapped[datetime | None] = ts(nullable=True)  # giờ cut-off ICD
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|matched|executing|completed|cancelled
    # trường nhạy cảm — kiểm soát riêng ở tầng ứng dụng (DRAFT 4.2)
    price_vnd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data_updated_at: Mapped[datetime] = ts(default_now=True)
    created_at: Mapped[datetime] = ts(default_now=True)


class ShipmentLeg(Base):
    __tablename__ = "shipment_legs"
    id: Mapped[uuid.UUID] = pk()
    shipment_id: Mapped[uuid.UUID] = fk("shipments.id")
    seq: Mapped[int] = mapped_column(Integer, default=1)
    from_location_id: Mapped[uuid.UUID] = fk("locations.id")
    to_location_id: Mapped[uuid.UUID] = fk("locations.id")


class LogisticsUnit(Base):
    __tablename__ = "logistics_units"
    id: Mapped[uuid.UUID] = pk()
    shipment_id: Mapped[uuid.UUID] = fk("shipments.id")
    leg_id: Mapped[uuid.UUID | None] = fk("shipment_legs.id", nullable=True)
    sscc: Mapped[str | None] = mapped_column(String(40), nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)


class ShipmentParticipant(Base):
    """Chia sẻ lô giữa các doanh nghiệp (DRAFT 4.2)."""
    __tablename__ = "shipment_participants"
    __table_args__ = (UniqueConstraint("shipment_id", "org_id"),)
    id: Mapped[uuid.UUID] = pk()
    shipment_id: Mapped[uuid.UUID] = fk("shipments.id")
    org_id: Mapped[uuid.UUID] = fk("organizations.id")
    role: Mapped[str] = mapped_column(String(20))  # shipper | carrier | node
    can_see_price: Mapped[bool] = mapped_column(Boolean, default=False)


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = fk("organizations.id")  # carrier sở hữu
    plate: Mapped[str] = mapped_column(String(20), unique=True)
    cargo_types: Mapped[list] = mapped_column(JSON)  # loại hàng chở được
    capacity_kg: Mapped[float] = mapped_column(Float)
    capacity_m3: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="available")  # available|committed|offline
    position_updated_at: Mapped[datetime | None] = ts(nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)  # vị trí GPS mới nhất (mô phỏng)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class AvailabilityWindow(Base):
    __tablename__ = "availability_windows"
    id: Mapped[uuid.UUID] = pk()
    vehicle_id: Mapped[uuid.UUID] = fk("vehicles.id")
    location_id: Mapped[uuid.UUID] = fk("locations.id")
    free_from: Mapped[datetime] = ts()
    free_to: Mapped[datetime] = ts()


class Slot(Base):
    __tablename__ = "slots"
    __table_args__ = (CheckConstraint("remaining >= 0 AND remaining <= capacity", name="ck_slot_remaining"),)
    id: Mapped[uuid.UUID] = pk()
    node_org_id: Mapped[uuid.UUID] = fk("organizations.id")
    location_id: Mapped[uuid.UUID] = fk("locations.id")
    start_at: Mapped[datetime] = ts()
    end_at: Mapped[datetime] = ts()
    capacity: Mapped[int] = mapped_column(Integer)
    remaining: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), default="mock")  # mock|manual_operator|partner_api
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("source_system", "source_event_id", name="uq_event_source"),)
    id: Mapped[uuid.UUID] = pk()  # event_id
    schema_version: Mapped[str] = mapped_column(String(10), default="1")
    tenant_id: Mapped[uuid.UUID] = fk("organizations.id")
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = ts()
    received_at: Mapped[datetime] = ts(default_now=True)
    source_system: Mapped[str] = mapped_column(String(40))
    source_event_id: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_status: Mapped[str] = mapped_column(String(20), default="ok")  # ok|late|corrected|invalid
    corrects_event_id: Mapped[uuid.UUID | None] = fk("events.id", nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExternalIdMap(Base):
    __tablename__ = "external_id_map"
    __table_args__ = (UniqueConstraint("tenant_id", "partner", "external_id"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = fk("organizations.id")
    partner: Mapped[str] = mapped_column(String(60))
    external_id: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))


class AssumptionSet(Base):
    __tablename__ = "assumption_sets"
    id: Mapped[uuid.UUID] = pk()
    version: Mapped[str] = mapped_column(String(30), unique=True)
    params: Mapped[dict] = mapped_column(JSON)  # trọng số, ngưỡng stale, đơn giá... (không hard-code UI)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # bản đang hiệu lực (tường minh, không suy từ created_at)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = ts(default_now=True)


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','pending_acceptance','confirmed','executing','completed',"
            "'rejected','expired','cancelled')", name="ck_proposal_status"),
    )
    id: Mapped[uuid.UUID] = pk()
    shipment_id: Mapped[uuid.UUID] = fk("shipments.id")
    vehicle_id: Mapped[uuid.UUID] = fk("vehicles.id")
    slot_id: Mapped[uuid.UUID | None] = fk("slots.id", nullable=True)
    # proposed|pending_acceptance|confirmed|executing|completed|rejected|expired|cancelled
    status: Mapped[str] = mapped_column(String(24), default="proposed")
    version: Mapped[int] = mapped_column(Integer, default=1)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_components: Mapped[dict] = mapped_column(JSON, default=dict)
    input_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    candidate_rejections: Mapped[list] = mapped_column(JSON, default=list)
    rule_version: Mapped[str] = mapped_column(String(30))
    model_version: Mapped[str] = mapped_column(String(30), default="rule-based")
    assumption_version: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[datetime | None] = ts(nullable=True)
    created_at: Mapped[datetime] = ts(default_now=True)


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("status IN ('held','committed','released','expired')", name="ck_reservation_status"),
        # Chống đặt trùng ở tầng DB (DRAFT 5.4): một tài nguyên chỉ có tối đa 1 reservation đang hiệu lực.
        # Chỉ áp cho tài nguyên đơn (xe, lô). Slot có capacity > 1 được bảo vệ bằng slots.remaining
        # (CHECK 0..capacity, cập nhật nguyên tử) — xem booking N2.
        Index("uq_reservation_active_resource", "resource_type", "resource_id", unique=True,
              postgresql_where=text("status IN ('held','committed') AND resource_type IN ('vehicle','shipment')")),
    )
    id: Mapped[uuid.UUID] = pk()
    proposal_id: Mapped[uuid.UUID] = fk("proposals.id")
    resource_type: Mapped[str] = mapped_column(String(20))  # vehicle | slot | shipment
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="held")  # held|committed|released|expired
    expires_at: Mapped[datetime] = ts()
    created_at: Mapped[datetime] = ts(default_now=True)


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        # Idempotency-Key unique theo tổ chức gửi (không toàn cục → không đụng key của tenant khác)
        UniqueConstraint("actor_org_id", "idempotency_key", name="uq_decision_org_idem"),
    )
    id: Mapped[uuid.UUID] = pk()
    proposal_id: Mapped[uuid.UUID] = fk("proposals.id")
    actor_user_id: Mapped[uuid.UUID] = fk("users.id")
    actor_org_id: Mapped[uuid.UUID] = fk("organizations.id")
    action: Mapped[str] = mapped_column(String(20))  # hold|accept|reject|resolve_exception
    party: Mapped[str | None] = mapped_column(String(10), nullable=True)  # carrier|shipper|node — bên đang xác nhận
    proposal_version: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    at: Mapped[datetime] = ts(default_now=True)


class ExceptionRecord(Base):
    __tablename__ = "exceptions"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_exceptions_dedupe_key"),)
    id: Mapped[uuid.UUID] = pk()
    proposal_id: Mapped[uuid.UUID] = fk("proposals.id")
    exc_type: Mapped[str] = mapped_column(String(30))  # ETA_CHANGED|DATA_STALE|SLOT_LOST ...
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|resolved
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = ts(default_now=True)
    # --- Exception Management (brief Control Tower, chức năng 5) ---
    severity: Mapped[str] = mapped_column(String(10), default="medium", server_default="medium")  # low|medium|high|critical — theo luật có version
    playbook_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    rule_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="event", server_default="event")  # event | sweep | manual
    sla_due_at: Mapped[datetime | None] = ts(nullable=True)
    escalated_at: Mapped[datetime | None] = ts(nullable=True)
    resolved_at: Mapped[datetime | None] = ts(nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True)


class ExceptionTask(Base):
    """Một bước của playbook: bước tự động (hệ thống làm) hoặc bước do người quyết (chủ thể có quyền hoàn tất)."""
    __tablename__ = "exception_tasks"
    id: Mapped[uuid.UUID] = pk()
    exception_id: Mapped[uuid.UUID] = fk("exceptions.id")
    step_key: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(10))  # auto | human
    owner: Mapped[str] = mapped_column(String(12))  # shipper | carrier | node | dispatcher | system
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | done
    position: Mapped[int] = mapped_column(Integer, default=0)
    completed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    completed_at: Mapped[datetime | None] = ts(nullable=True)


class Notification(Base):
    """Thông báo cho người nhận. sms_sim/email_sim là NHẬT KÝ GIẢ LẬP (không gọi nhà cung cấp thật, không chứa PII)."""
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_recipient", "recipient_org_id", "recipient_role", "created_at"),)
    id: Mapped[uuid.UUID] = pk()
    exception_id: Mapped[uuid.UUID | None] = fk("exceptions.id", nullable=True)
    recipient_org_id: Mapped[uuid.UUID | None] = fk("organizations.id", nullable=True)
    recipient_role: Mapped[str | None] = mapped_column(String(20), nullable=True)  # None = mọi người trong tổ chức
    channel: Mapped[str] = mapped_column(String(10), default="in_app")  # in_app | sms_sim | email_sim
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = ts(default_now=True)
    read_at: Mapped[datetime | None] = ts(nullable=True)


class BenefitLedger(Base):
    __tablename__ = "benefit_ledger"
    __table_args__ = (
        # mỗi chuyến + baseline + hạng mục chỉ ghi một lần (event TRIP_COMPLETED gửi lại không nhân đôi lợi ích)
        UniqueConstraint("shipment_id", "baseline_id", "cost_category", name="uq_benefit_once"),
        CheckConstraint("status IN ('estimated','measured','verified')", name="ck_benefit_status"),
    )
    id: Mapped[uuid.UUID] = pk()
    shipment_id: Mapped[uuid.UUID] = fk("shipments.id")
    proposal_id: Mapped[uuid.UUID | None] = fk("proposals.id", nullable=True)
    baseline_id: Mapped[str] = mapped_column(String(60))
    cost_category: Mapped[str] = mapped_column(String(40))
    quantity_before: Mapped[float] = mapped_column(Float)
    quantity_after: Mapped[float] = mapped_column(Float)
    unit_rate: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="VND")
    assumption_version: Mapped[str] = mapped_column(String(30))
    beneficiary_org_id: Mapped[uuid.UUID] = fk("organizations.id")
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="estimated")  # estimated|measured|verified
    verifier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verified_at: Mapped[datetime | None] = ts(nullable=True)


class OutboxJob(Base):
    __tablename__ = "outbox_jobs"
    id: Mapped[uuid.UUID] = pk()
    topic: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = ts(nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = ts(default_now=True)


class TripTrack(Base):
    """Vệt di chuyển của một chuyến (breadcrumb). Giới hạn số điểm/chuyến ở tracking.service."""
    __tablename__ = "trip_tracks"
    __table_args__ = (Index("ix_trip_tracks_proposal_at", "proposal_id", "at"),)
    id: Mapped[uuid.UUID] = pk()
    proposal_id: Mapped[uuid.UUID] = fk("proposals.id")
    vehicle_id: Mapped[uuid.UUID] = fk("vehicles.id")
    at: Mapped[datetime] = ts()
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="gps")  # gps | sim-gps


class SimTrip(Base):
    """Trạng thái bộ giả lập GPS của một chuyến (chỉ dùng cho demo/mô phỏng)."""
    __tablename__ = "sim_trips"
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("proposals.id"), primary_key=True)
    running: Mapped[bool] = mapped_column(Boolean, default=True)
    mode: Mapped[str] = mapped_column(String(12), default="normal")  # normal | slow | breakdown | detour
    along_km: Mapped[float] = mapped_column(Float, default=0.0)
    time_scale: Mapped[float] = mapped_column(Float, default=20.0)  # tăng tốc thời gian mô phỏng để demo ngắn
    seq: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = ts(default_now=True)
