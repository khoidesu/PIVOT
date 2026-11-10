"""Sổ lợi ích (DRAFT 11.1): mỗi chuyến hoàn tất có baseline (chốt trước quyết định), actual, đơn vị, nguồn, người hưởng lợi,
bằng chứng và mức xác minh. Tách estimated / measured / verified — không gộp thành một tổng 'tiết kiệm'.

  estimated: tính từ ETA/khoảng cách luật (rule-based) khi hoàn tất
  measured : nhà vận tải báo số đo thực (TRIP_COMPLETED.payload.actual_empty_km)
  verified : bên đối tác xác nhận số đo (chỉ từ measured)
Lợi ích ròng = (baseline − actual) × đơn giá. Mỗi (chuyến, baseline, hạng mục) chỉ ghi MỘT lần (unique).
"""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import Actor
from ..booking import service as bk

CATEGORY = "empty_km"
STATUSES = ("estimated", "measured", "verified")


def net_vnd(row: m.BenefitLedger) -> int:
    return int(round((row.quantity_before - row.quantity_after) * row.unit_rate))


def record_completion(session: Session, prop: m.Proposal, ev: m.Event, ship: m.Shipment, veh: m.Vehicle) -> m.BenefitLedger | None:
    snap = prop.input_snapshot or {}
    base = snap.get("baseline") or {}
    if "empty_km" not in base:
        return None
    exists = session.execute(select(m.BenefitLedger).where(
        m.BenefitLedger.shipment_id == ship.id, m.BenefitLedger.baseline_id == base["id"],
        m.BenefitLedger.cost_category == CATEGORY)).scalar_one_or_none()
    if exists:
        return exists
    actual = (ev.payload or {}).get("actual_empty_km")
    measured = actual is not None
    row = m.BenefitLedger(
        shipment_id=ship.id, proposal_id=prop.id, baseline_id=base["id"], cost_category=CATEGORY,
        quantity_before=float(base["empty_km"]),
        quantity_after=float(actual) if measured else float(snap.get("deadhead_km") or 0.0),
        unit_rate=float(base["cost_per_km_vnd"]), currency="VND", assumption_version=prop.assumption_version,
        beneficiary_org_id=veh.tenant_id,
        evidence_refs=[{"type": "proposal", "id": str(prop.id)}, {"type": "event", "id": str(ev.id)},
                       {"type": "match_run", "id": snap.get("run_id")}],
        status="measured" if measured else "estimated")
    session.add(row)
    session.flush()
    return row


def _orgs(session: Session, row: m.BenefitLedger):
    prop = session.get(m.Proposal, row.proposal_id)
    ship = session.get(m.Shipment, prop.shipment_id)
    veh = session.get(m.Vehicle, prop.vehicle_id)
    slot = session.get(m.Slot, prop.slot_id) if prop.slot_id else None
    return prop, ship, veh, bk.party_orgs(ship, veh, slot)


def can_verify(actor: Actor, orgs: dict, row: m.BenefitLedger) -> bool:
    """Đối tác xác nhận: chủ lô hoặc nhà vận tải của chuyến (vai shipper/carrier); điều phối viên và node không xác minh."""
    return (row.status == "measured" and actor.role in ("shipper", "carrier")
            and actor.org_id in (orgs.get("shipper"), orgs.get("carrier")))


def visible(actor: Actor, orgs: dict) -> bool:
    return actor.role == "dispatcher" or actor.org_id in (orgs.get("shipper"), orgs.get("carrier"))


def view(session: Session, actor: Actor, row: m.BenefitLedger, detail: bool = False) -> dict | None:
    prop, ship, veh, orgs = _orgs(session, row)
    if not visible(actor, orgs):
        return None
    org = session.get(m.Organization, row.beneficiary_org_id)
    out = {
        "id": row.id, "proposal_id": row.proposal_id, "shipment_code": ship.code, "vehicle_plate": veh.plate,
        "cost_category": row.cost_category, "quantity_before": row.quantity_before, "quantity_after": row.quantity_after,
        "unit": "km", "unit_rate": row.unit_rate, "currency": row.currency, "net_vnd": net_vnd(row),
        "status": row.status, "baseline_id": row.baseline_id, "assumption_version": row.assumption_version,
        "beneficiary_org_name": org.name if org else None, "verifier": row.verifier, "verified_at": row.verified_at,
        "can_verify": can_verify(actor, orgs, row), "is_simulated": True,
    }
    if detail:
        aset = session.execute(select(m.AssumptionSet).where(m.AssumptionSet.version == row.assumption_version)).scalar_one_or_none()
        events = []
        for ref in row.evidence_refs or []:
            if ref.get("type") == "event":
                ev = session.get(m.Event, uuid.UUID(ref["id"]))
                if ev:
                    events.append({"id": ev.id, "event_type": ev.event_type, "source_system": ev.source_system,
                                   "occurred_at": ev.occurred_at, "received_at": ev.received_at,
                                   "quality_status": ev.quality_status, "payload": ev.payload})
        out |= {"evidence": events, "evidence_refs": row.evidence_refs,
                "baseline": (prop.input_snapshot or {}).get("baseline"),
                "assumptions": {k: v for k, v in (aset.params if aset else {}).items() if k in ("cost_per_km_vnd", "empty_km_baseline", "eta_method")},
                "formula": {"before": row.quantity_before, "after": row.quantity_after, "rate": row.unit_rate}}
    return out


def verify(session: Session, actor: Actor, benefit_id: uuid.UUID, now: datetime) -> m.BenefitLedger:
    row = session.execute(select(m.BenefitLedger).where(m.BenefitLedger.id == benefit_id).with_for_update()).scalar_one_or_none()
    if row is None:
        raise bk.BookingError("NOT_FOUND", "Benefit not found", 404)
    _, _, _, orgs = _orgs(session, row)
    if not visible(actor, orgs):
        raise bk.BookingError("NOT_FOUND", "Benefit not found", 404)
    if actor.role not in ("shipper", "carrier") or actor.org_id not in (orgs.get("shipper"), orgs.get("carrier")):
        raise bk.BookingError("FORBIDDEN", "Only the shipper or carrier of this trip can verify", 403)
    if row.status == "verified":
        return row  # idempotent
    if row.status != "measured":
        raise bk.BookingError("NOT_MEASURED", "Only a measured benefit can be verified (estimates cannot)", 409)
    row.status, row.verifier, row.verified_at = "verified", f"{actor.user_name} ({actor.org_name})", now
    session.flush()
    return row


def totals(rows: list[dict]) -> dict:
    out = {s: {"count": 0, "net_vnd": 0} for s in STATUSES}
    for r in rows:
        out[r["status"]]["count"] += 1
        out[r["status"]]["net_vnd"] += r["net_vnd"]
    return out
