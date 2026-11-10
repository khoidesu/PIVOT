import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    ready_at: datetime
    pickup_deadline: datetime
    cutoff_at: datetime
    price_vnd: int | None = Field(default=None, ge=0)
    customer_name: str | None = None


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
