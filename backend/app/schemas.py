import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


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


class ShipmentCreate(BaseModel):
    """Yêu cầu hợp lệ: thiếu trường bắt buộc → 422, không tạo lô (DRAFT mục 8/ngày 4)."""
    code: str = Field(min_length=3, max_length=40)
    cargo_type: str = Field(min_length=2, max_length=30)
    weight_kg: float = Field(gt=0)
    volume_m3: float = Field(gt=0)
    origin_location_id: uuid.UUID
    dest_location_id: uuid.UUID
    ready_at: AwareDatetime  # bắt buộc có múi giờ (lưu UTC, DRAFT mục 4.1)
    pickup_deadline: AwareDatetime
    cutoff_at: AwareDatetime
    price_vnd: int | None = Field(default=None, ge=0)
    customer_name: str | None = None

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


class SlotOut(ORM):
    id: uuid.UUID
    node_org_id: uuid.UUID
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
from typing import Any  # noqa: E402


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


class MatchRunIn(BaseModel):
    shipment_id: uuid.UUID


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


class ActionIn(BaseModel):
    version: int = Field(ge=1)


class EventIn(BaseModel):
    entity_id: uuid.UUID
    event_type: str = Field(min_length=3, max_length=40)
    occurred_at: AwareDatetime
    source_system: str = Field(min_length=1, max_length=40)
    source_event_id: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = {}
    correlation_id: str | None = Field(default=None, max_length=64)


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
