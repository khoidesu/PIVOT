"""Tối thiểu hoá dữ liệu (DRAFT slide governance: "một đề xuất chỉ hiện dữ liệu đủ dùng").

Danh sách xe BỊ LOẠI chứa chi tiết đội xe của nhà vận tải khác (tải trọng, tuổi vị trí, loại hàng chở được…).
Người xem không phải chủ xe (và không phải điều phối viên) chỉ thấy mã lý do + dữ kiện thuộc về CHÍNH lô của họ.
Bản đầy đủ vẫn lưu nguyên trong DB để audit/replay.
"""
import uuid

from ..auth import Actor

# dữ kiện được giữ lại theo reason_code (chỉ thông tin của lô/slot, không lộ đội xe)
SAFE_KEYS = {
    "CAPACITY_EXCEEDED": ("weight_kg", "volume_m3", "over"),
    "CARGO_INCOMPATIBLE": ("cargo_type",),
    "DATA_STALE": ("limit_minutes", "subject"),
    "PICKUP_WINDOW_MISSED": ("pickup_deadline",),
    "CUTOFF_RISK": ("cutoff_at",),
    "VEHICLE_UNAVAILABLE": ("reserved",),
    "SLOT_FULL": (), "SLOT_WINDOW_MISSED": ("slot_end_at",),  # giờ của slot (không phải ETA xe bên khác)
     "SLOT_LOCATION_MISMATCH": (), "SLOT_AFTER_CUTOFF": ("slot_start_at", "cutoff_at"),
    "MISSING_FIELD": ("missing",), "SHIPMENT_NOT_OPEN": ("status",), "ID_UNRESOLVED": (),
}
OWN_SHIPMENT_GATES = {"shipment_fresh", "shipment_open"}  # gate về chính lô của người xem → giữ nguyên


def mask_plate(plate: str) -> str:
    return plate[:4] + "•••" + plate[-3:] if len(plate) > 8 else "•••"


def redact_rejections(items: list[dict], vehicle_org: dict[str, uuid.UUID], actor: Actor) -> list[dict]:
    out = []
    for r in items or []:
        if actor.role == "dispatcher" or vehicle_org.get(r["vehicle_id"]) == actor.org_id:
            out.append(r)
            continue
        reasons = []
        for x in r["reasons"]:
            if x["gate"] in OWN_SHIPMENT_GATES:
                reasons.append(x)
                continue
            keep = SAFE_KEYS.get(x["reason_code"], ())
            reasons.append({**x, "detail": {**{k: x["detail"][k] for k in keep if k in x["detail"]}, "redacted": True}})
        # bãi đậu + km là thông tin đội xe của nhà vận tải khác → bỏ khỏi bản cho người không phải chủ xe
        out.append({**{k: v for k, v in r.items() if k not in ("yard", "yard_km")}, "plate": mask_plate(r["plate"]), "reasons": reasons})
    return out
