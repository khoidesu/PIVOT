import math
import uuid
from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_PRICE_VND = 10 ** 15  # trần hợp lý (1 triệu tỷ ₫) và nằm xa giới hạn BIGINT của DB
# Trần kích thước một lô (QA-04): rộng hơn nhiều so với xe lớn nhất (đầu kéo ~30 t / ~70 m³) và dữ liệu seed/sandbox (≤ 21 t, ≤ 44 m³)
# để không chặn lô hợp lệ nào, nhưng chặn số vô lý (1e300…) trước khi vào DB/ghép. Lô vượt tải xe vẫn được tạo và bị hard gate loại.
MAX_WEIGHT_KG = 100_000.0
MAX_VOLUME_M3 = 500.0


class In(BaseModel):
    """Gốc cho mọi body ĐẦU VÀO: số thực phải hữu hạn (NaN/Infinity/1e309 → 422, không vào DB — QA-04)."""
    model_config = ConfigDict(allow_inf_nan=False)


def finite_json(v: Any, path: str = "payload") -> Any:
    """Duyệt dữ liệu JSON tự do (dict/list lồng nhau): từ chối số không hữu hạn ở BẤT KỲ đâu — Postgres JSON không lưu được NaN/Infinity
    (trước đây → 500) và worker không được nhận số vô nghĩa."""
    if isinstance(v, float) and not math.isfinite(v):
        raise ValueError(f"{path} must be a finite number")
    if isinstance(v, dict):
        for k, x in v.items():
            finite_json(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            finite_json(x, f"{path}[{i}]")
    return v


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MeOut(BaseModel):
    user_id: uuid.UUID
    user_name: str
    org_id: uuid.UUID
    org_name: str
    org_type: str
    role: str


class MetaOut(BaseModel):
    data_mode: str  # mock | live
    is_simulated: bool
    server_time: datetime
    stale_position_minutes: int
    stale_shipment_minutes: int = 60
    admin_key_required: bool = False
    image_intake_enabled: bool = False
    pdf_intake_enabled: bool = False


class ShipmentCreate(In):
    """Yêu cầu hợp lệ: thiếu trường bắt buộc → 422, không tạo lô (DRAFT mục 8/ngày 4)."""
    code: str = Field(min_length=3, max_length=40)
    cargo_type: str = Field(min_length=2, max_length=30)
    weight_kg: float = Field(gt=0, le=MAX_WEIGHT_KG)
    volume_m3: float = Field(gt=0, le=MAX_VOLUME_M3)
    origin_location_id: uuid.UUID
    dest_location_id: uuid.UUID
    ready_at: AwareDatetime  # bắt buộc có múi giờ (lưu UTC, DRAFT mục 4.1)
    pickup_deadline: AwareDatetime
    cutoff_at: AwareDatetime
    price_vnd: int | None = Field(default=None, ge=0, le=MAX_PRICE_VND)
    customer_name: str | None = Field(default=None, max_length=200)  # khớp cột String(200): quá dài → 422 thay vì lỗi DB (500)
    draft_id: uuid.UUID | None = None  # nếu tạo từ bản nháp nhập liệu đã được người dùng duyệt

    @model_validator(mode="after")
    def _time_order(self):
        if not (self.ready_at < self.pickup_deadline < self.cutoff_at):
            raise ValueError("require ready_at < pickup_deadline < cutoff_at")
        return self


class ShipmentOut(ORM):
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    cargo_type: str
    weight_kg: float | None
    volume_m3: float | None
    origin_location_id: uuid.UUID
    dest_location_id: uuid.UUID
    ready_at: datetime
    pickup_deadline: datetime | None
    cutoff_at: datetime | None
    status: str
    is_simulated: bool
    version: int
    data_updated_at: datetime
    # nhạy cảm — None nếu actor không có quyền
    price_vnd: int | None = None
    customer_name: str | None = None
    missing_fields: list[str] = []


class YardOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    lat: float
    lng: float


class VehicleOut(ORM):
    id: uuid.UUID
    tenant_id: uuid.UUID
    plate: str
    cargo_types: list[str]
    capacity_kg: float
    capacity_m3: float
    status: str
    position_updated_at: datetime | None
    is_simulated: bool
    # Bãi đang đậu + trạng thái dễ hiểu + khoảng cách tới điểm cần tới (ƯỚC TÍNH, nhãn `distance_method`)
    yard: YardOut | None = None
    free_from: datetime | None = None
    free_to: datetime | None = None
    availability: dict[str, str] | None = None
    position_age_seconds: int | None = None
    distance_to_target_km: float | None = None
    distance_method: str | None = None
    deadhead_eta: dict[str, Any] | None = None


class SlotOut(ORM):
    id: uuid.UUID
    node_org_id: uuid.UUID
    node_org_name: str | None = None
    location_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    capacity: int
    remaining: int
    source: str
    is_simulated: bool


class LocationOut(ORM):
    id: uuid.UUID
    name: str
    kind: str
    lat: float
    lng: float


# ---------------- ghép (match-runs), đề xuất, sự kiện ----------------


class ShipmentBrief(ORM):
    id: uuid.UUID
    code: str
    cargo_type: str
    weight_kg: float | None
    volume_m3: float | None
    ready_at: datetime
    pickup_deadline: datetime | None
    cutoff_at: datetime | None
    origin_location_id: uuid.UUID
    dest_location_id: uuid.UUID
    status: str


class VehicleBrief(BaseModel):
    id: uuid.UUID
    plate: str
    capacity_kg: float
    capacity_m3: float
    carrier_org_name: str | None
    yard: str | None = None  # bãi đang đậu lúc ghép (từ snapshot; đề xuất cũ không có)


class SlotBrief(BaseModel):
    id: uuid.UUID
    start_at: datetime
    end_at: datetime
    remaining: int
    capacity: int
    source: str  # mock | manual_operator | partner_api
    node_org_name: str | None


class PartyState(BaseModel):
    org_name: str | None
    accepted: bool


class MyActions(BaseModel):
    hold: bool
    accept: bool
    reject: bool


class ProposalOut(BaseModel):
    id: uuid.UUID
    status: str
    version: int
    is_simulated: bool
    confirmation_source: str | None
    shipment: ShipmentBrief
    vehicle: VehicleBrief
    slot: SlotBrief | None
    score: float | None
    score_components: dict[str, Any]
    estimated_saving_vnd: int | None
    deadhead_km: float | None
    eta: dict[str, Any] | None
    gates: list[dict[str, Any]]
    rejections: list[dict[str, Any]]
    rule_version: str
    model_version: str
    assumption_version: str
    expires_at: datetime | None
    hold_seconds_left: int | None
    parties: dict[str, PartyState]
    my_actions: MyActions
    run_id: str | None
    created_at: datetime


class MatchRunIn(In):
    shipment_id: uuid.UUID
    node_org_id: uuid.UUID | None = None  # chủ hàng chọn ICD; bỏ trống → luân phiên giữa các ICD có slot đạt


class MatchRunOut(BaseModel):
    run_id: str
    status: str  # proposals | no_feasible_option | needs_data
    proposals: list[ProposalOut]
    rejections: list[dict[str, Any]]
    needs_data: list[dict[str, Any]]
    rule_version: str
    assumption_version: str
    generated_at: datetime
    evaluated_vehicles: int
    eta_method: str


class ActionIn(In):
    version: int = Field(ge=1)


class EventIn(In):
    entity_type: str = Field(default="proposal", pattern="^(proposal|vehicle)$")
    entity_id: uuid.UUID
    event_type: str = Field(min_length=3, max_length=40)
    occurred_at: AwareDatetime
    source_system: str = Field(min_length=1, max_length=40)
    source_event_id: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = {}
    correlation_id: str | None = Field(default=None, max_length=64)

    @field_validator("payload")
    @classmethod
    def _finite_payload(cls, v: dict[str, Any]) -> dict[str, Any]:
        return finite_json(v)


class EventOut(BaseModel):
    event_id: uuid.UUID
    duplicate: bool
    quality_status: str


class ExceptionOut(ORM):
    id: uuid.UUID
    proposal_id: uuid.UUID
    exc_type: str
    status: str
    detail: dict[str, Any]
    created_at: datetime


class OutboxOut(ORM):
    id: uuid.UUID
    topic: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime


# ---------------- timeline, replay, lợi ích, demo ----------------
class TimelineItem(BaseModel):
    at: datetime
    kind: str  # match | decision | event | exception | benefit
    code: str
    actor: str | None
    quality: str | None
    latency_s: int | None
    detail: dict[str, Any]


class TimelineOut(BaseModel):
    proposal_id: uuid.UUID
    status: str
    version: int
    shipment_code: str
    items: list[TimelineItem]


class ReplayOut(BaseModel):
    proposal_id: uuid.UUID
    stored_score: float | None
    recomputed_score: float
    reproducible: bool
    weights_sum: float | None
    all_gates_pass: bool
    gate_count: int
    rejected_candidates: int
    rule_version: str
    model_version: str
    assumption_version: str
    run_id: str | None
    baseline: dict[str, Any] | None
    snapshot_keys: list[str]


class ResolveIn(In):
    resolution: str = Field(pattern="^(accept_delay|request_replan)$")
    note: str | None = Field(default=None, max_length=500)


class BenefitOut(BaseModel):
    id: uuid.UUID
    proposal_id: uuid.UUID | None
    shipment_code: str
    vehicle_plate: str
    cost_category: str
    quantity_before: float
    quantity_after: float
    unit: str
    unit_rate: float
    currency: str
    net_vnd: int
    status: str  # estimated | measured | verified
    baseline_id: str
    assumption_version: str
    beneficiary_org_name: str | None
    verifier: str | None
    verified_at: datetime | None
    can_verify: bool
    verifier_independent_available: bool = True
    is_simulated: bool
    evidence: list[dict[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = []
    baseline: dict[str, Any] | None = None
    assumptions: dict[str, Any] = {}
    formula: dict[str, Any] | None = None


class BenefitListOut(BaseModel):
    items: list[BenefitOut]
    totals: dict[str, dict[str, int]]


class ShipmentUpdate(In):
    """Sửa yêu cầu: chỉ các trường gửi lên được đổi; `version` bắt buộc (khoá lạc quan)."""
    version: int = Field(ge=1)
    cargo_type: str | None = Field(default=None, min_length=2, max_length=30)
    weight_kg: float | None = Field(default=None, gt=0, le=MAX_WEIGHT_KG)
    volume_m3: float | None = Field(default=None, gt=0, le=MAX_VOLUME_M3)
    origin_location_id: uuid.UUID | None = None
    dest_location_id: uuid.UUID | None = None
    ready_at: AwareDatetime | None = None
    pickup_deadline: AwareDatetime | None = None
    cutoff_at: AwareDatetime | None = None
    price_vnd: int | None = Field(default=None, ge=0, le=MAX_PRICE_VND)
    customer_name: str | None = Field(default=None, max_length=200)


class IntakeIn(In):
    text: str = Field(min_length=1, max_length=8000)


class IntakeFieldOut(BaseModel):
    value: Any = None
    display: str | None = None
    source: dict[str, Any] | None = None
    status: str  # ok | needs_review
    notes: list[str] = []


class IntakeImageIn(In):
    image_base64: str = Field(min_length=100, max_length=6_000_000)  # ảnh đã được trình duyệt thu nhỏ; máy chủ vẫn kiểm tra loại + kích thước thật


class IntakeFileIn(In):
    file_base64: str = Field(min_length=100, max_length=7_000_000)  # ảnh (đã thu nhỏ) hoặc PDF ≤ 5 MB; máy chủ kiểm tra loại theo nội dung + kích thước thật


class IntakeDraftOut(BaseModel):
    draft_id: str
    extractor: dict[str, str]
    source: dict[str, Any]
    reference_time: str
    fields: dict[str, IntakeFieldOut]
    needs_review: list[str]
    complete: bool
    suspicious_instructions: bool
    is_draft_only: bool
    transcript: str | None = None  # bản nháp từ ảnh/PDF: chữ đọc được (để người dùng đối chiếu)
    image_quota_remaining: int | None = None
