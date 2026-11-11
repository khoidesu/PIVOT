"""Hard gate (DRAFT 5.1): mỗi điều kiện là một hàm thuần trả PASS | FAIL | UNKNOWN + reason_code.

- Chạy TẤT CẢ gate (không dừng sớm) để lưu đủ lý do loại vào candidate_rejections.
- Trường bắt buộc thiếu → UNKNOWN (cần bổ sung dữ liệu), KHÔNG bao giờ âm thầm PASS.
- FAIL ưu tiên hơn UNKNOWN: có điều kiện đã vi phạm chắc chắn thì loại luôn.
- Thông số (ngưỡng stale, thời gian ETA luật…) đến từ assumption_set có version.
- Không đụng DB: nhận object đã nạp, dễ test.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

Status = Literal["PASS", "FAIL", "UNKNOWN"]

# reason_code (DRAFT 5.1) + MISSING_FIELD cho trường bắt buộc còn thiếu
CARGO_INCOMPATIBLE = "CARGO_INCOMPATIBLE"
CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"
PICKUP_WINDOW_MISSED = "PICKUP_WINDOW_MISSED"
CUTOFF_RISK = "CUTOFF_RISK"
VEHICLE_UNAVAILABLE = "VEHICLE_UNAVAILABLE"
SLOT_FULL = "SLOT_FULL"
DATA_STALE = "DATA_STALE"
ID_UNRESOLVED = "ID_UNRESOLVED"
SLOT_WINDOW_MISSED = "SLOT_WINDOW_MISSED"  # xe tới ICD sau khung giờ của slot
SLOT_LOCATION_MISMATCH = "SLOT_LOCATION_MISMATCH"  # slot không ở điểm đến của lô
SLOT_AFTER_CUTOFF = "SLOT_AFTER_CUTOFF"  # slot bắt đầu sau giờ cut-off của lô
MISSING_FIELD = "MISSING_FIELD"
OK = "OK"


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: Status
    reason_code: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    status: Status  # tổng hợp
    results: list[GateResult]
    rule_version: str

    @property
    def rejections(self) -> list[GateResult]:
        return [r for r in self.results if r.status != "PASS"]


def _unknown(gate: str, *fields: str) -> GateResult:
    return GateResult(gate, "UNKNOWN", MISSING_FIELD, {"missing": list(fields)})


def gate_data_fresh(vehicle, now: datetime, params: dict) -> GateResult:
    if vehicle.position_updated_at is None:
        return _unknown("data_fresh", "vehicle.position_updated_at")
    age = (now - vehicle.position_updated_at).total_seconds() / 60
    limit = params["stale_position_minutes"]
    if age > limit:
        return GateResult("data_fresh", "FAIL", DATA_STALE, {"age_minutes": round(age, 1), "limit_minutes": limit})
    return GateResult("data_fresh", "PASS", OK, {"age_minutes": round(age, 1), "limit_minutes": limit})


def gate_shipment_fresh(shipment, now: datetime, params: dict) -> GateResult:
    """Tuổi dữ liệu của LÔ (DRAFT 5.1 bắt đầu bằng 'kiểm tra quyền & tuổi dữ liệu')."""
    if shipment.data_updated_at is None:
        return _unknown("shipment_fresh", "shipment.data_updated_at")
    age = max((now - shipment.data_updated_at).total_seconds() / 60, 0.0)  # đồng hồ lệch → coi như 0
    limit = params["stale_shipment_minutes"]
    detail = {"age_minutes": round(age, 1), "limit_minutes": limit, "subject": "shipment"}
    if age > limit:
        return GateResult("shipment_fresh", "FAIL", DATA_STALE, detail)
    return GateResult("shipment_fresh", "PASS", OK, detail)


def gate_cargo(shipment, vehicle) -> GateResult:
    if not shipment.cargo_type:
        return _unknown("cargo", "shipment.cargo_type")
    if shipment.cargo_type not in (vehicle.cargo_types or []):
        return GateResult("cargo", "FAIL", CARGO_INCOMPATIBLE,
                          {"cargo_type": shipment.cargo_type, "vehicle_accepts": vehicle.cargo_types})
    return GateResult("cargo", "PASS", OK, {"cargo_type": shipment.cargo_type})


def gate_capacity(shipment, vehicle) -> GateResult:
    missing = [f"shipment.{f}" for f in ("weight_kg", "volume_m3") if getattr(shipment, f) is None]
    if missing:
        return _unknown("capacity", *missing)
    over_kg = shipment.weight_kg > vehicle.capacity_kg
    over_m3 = shipment.volume_m3 > vehicle.capacity_m3
    detail = {"weight_kg": shipment.weight_kg, "capacity_kg": vehicle.capacity_kg,
              "volume_m3": shipment.volume_m3, "capacity_m3": vehicle.capacity_m3}
    if over_kg or over_m3:
        return GateResult("capacity", "FAIL", CAPACITY_EXCEEDED, detail)
    return GateResult("capacity", "PASS", OK, detail)


def gate_vehicle_available(vehicle, window, reserved: bool = False) -> GateResult:
    if reserved:  # xe đang bị giữ/cam kết bởi một đề xuất khác
        return GateResult("vehicle_available", "FAIL", VEHICLE_UNAVAILABLE,
                          {"status": vehicle.status, "reserved": True})
    if vehicle.status != "available":
        return GateResult("vehicle_available", "FAIL", VEHICLE_UNAVAILABLE, {"status": vehicle.status})
    if window is None:
        return _unknown("vehicle_available", "availability_window")
    return GateResult("vehicle_available", "PASS", OK, {"status": vehicle.status})


def pickup_eta(window, shipment, now: datetime, params: dict) -> datetime | None:
    """ETA luật (rule-based): xe rảnh + thời gian tới điểm lấy; không sớm hơn giờ hàng sẵn sàng."""
    if window is None or shipment.ready_at is None:
        return None
    start = max(window.free_from, now)
    return max(start + timedelta(minutes=params["deadhead_minutes"]), shipment.ready_at)


def gate_pickup_window(shipment, window, now: datetime, params: dict) -> GateResult:
    if shipment.pickup_deadline is None:
        return _unknown("pickup_window", "shipment.pickup_deadline")
    eta = pickup_eta(window, shipment, now, params)
    if eta is None:
        return _unknown("pickup_window", "availability_window")
    detail = {"eta_pickup": eta.isoformat(), "pickup_deadline": shipment.pickup_deadline.isoformat(),
              "eta_method": params.get("eta_method", "rule-based")}
    if eta > shipment.pickup_deadline or eta > window.free_to:
        return GateResult("pickup_window", "FAIL", PICKUP_WINDOW_MISSED, detail)
    return GateResult("pickup_window", "PASS", OK, detail)


def gate_cutoff(shipment, window, now: datetime, params: dict) -> GateResult:
    if shipment.cutoff_at is None:
        return _unknown("cutoff", "shipment.cutoff_at")
    eta = pickup_eta(window, shipment, now, params)
    if eta is None:
        return _unknown("cutoff", "availability_window")
    arrive_icd = eta + timedelta(minutes=params["transit_minutes"] + params["handling_minutes"])
    detail = {"eta_icd": arrive_icd.isoformat(), "cutoff_at": shipment.cutoff_at.isoformat()}
    if arrive_icd > shipment.cutoff_at:
        return GateResult("cutoff", "FAIL", CUTOFF_RISK, detail)
    return GateResult("cutoff", "PASS", OK, detail)


def gate_slot(slot, shipment, window, now: datetime, params: dict) -> GateResult:
    if slot is None:
        return _unknown("slot", "slot")
    detail = {"slot_id": str(slot.id), "remaining": slot.remaining, "source": slot.source}
    if slot.location_id != shipment.dest_location_id:
        return GateResult("slot", "FAIL", SLOT_LOCATION_MISMATCH,
                          detail | {"slot_location_id": str(slot.location_id),
                                    "dest_location_id": str(shipment.dest_location_id)})
    if shipment.cutoff_at is not None and slot.start_at > shipment.cutoff_at:  # lịch hẹn ở ICD phải nằm trước giờ chốt của lô
        return GateResult("slot", "FAIL", SLOT_AFTER_CUTOFF,
                          detail | {"slot_start_at": slot.start_at.isoformat(), "cutoff_at": shipment.cutoff_at.isoformat()})
    if slot.remaining <= 0:
        return GateResult("slot", "FAIL", SLOT_FULL, detail)
    eta = pickup_eta(window, shipment, now, params)
    if eta is not None:
        arrive_icd = eta + timedelta(minutes=params["transit_minutes"] + params["handling_minutes"])
        detail["eta_icd"] = arrive_icd.isoformat()
        if arrive_icd > slot.end_at:
            return GateResult("slot", "FAIL", SLOT_WINDOW_MISSED, detail | {"slot_end_at": slot.end_at.isoformat()})
    return GateResult("slot", "PASS", OK, detail)


def evaluate(shipment, vehicle, window, slot, now: datetime, params: dict,
             vehicle_reserved: bool = False) -> Verdict:
    results = [
        gate_data_fresh(vehicle, now, params),
        gate_shipment_fresh(shipment, now, params),
        gate_cargo(shipment, vehicle),
        gate_capacity(shipment, vehicle),
        gate_vehicle_available(vehicle, window, vehicle_reserved),
        gate_pickup_window(shipment, window, now, params),
        gate_cutoff(shipment, window, now, params),
        gate_slot(slot, shipment, window, now, params),
    ]
    if any(r.status == "FAIL" for r in results):
        overall: Status = "FAIL"
    elif any(r.status == "UNKNOWN" for r in results):
        overall = "UNKNOWN"
    else:
        overall = "PASS"
    return Verdict(overall, results, params["rule_version"])
