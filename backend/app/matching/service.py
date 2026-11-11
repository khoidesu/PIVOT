"""Chạy một lượt ghép (DRAFT 5.1): quyền & tuổi dữ liệu → lọc ứng viên gần phù hợp → hard gate → ước tính lợi ích →
xếp hạng → lưu đề xuất. Hard gate chạy TRƯỚC score; ứng viên FAIL/UNKNOWN không bao giờ được chấm điểm.
Không có ứng viên đạt → "không có phương án khả thi" kèm lý do (không ép ghép).
"""
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..assumptions import get_active
from ..auth import Actor
from ..booking import service as bk
from ..eta import baseline as eta_mod
from . import gates, score

RUN_ROLES = {"shipper", "carrier", "dispatcher"}


def _loc(locs: dict, location_id):
    return locs[location_id]


def _spread_icds(top: list, slots: list, shipment: m.Shipment, now: datetime, params: dict, reserved_vehicles: set) -> None:
    """Nhiều ICD cùng có slot đạt tại điểm đến → các đề xuất luân phiên giữa các ICD (theo thứ tự giờ slot sớm nhất của mỗi ICD),
    để mọi ICD đều nhận được yêu cầu xác nhận. Trước đây luôn lấy slot sớm nhất nên ICD có nhiều slot sớm hơn "nuốt" hết đề xuất.
    Slot mới vẫn phải qua hard gate (đánh giá lại); không đạt thì giữ slot cũ. Chỉ một ICD → không đổi gì."""
    nodes: list = []
    for sl in slots:
        if sl.node_org_id not in nodes:
            nodes.append(sl.node_org_id)
    if len(nodes) < 2:
        return
    for i, e in enumerate(top):
        want = nodes[i % len(nodes)]
        if e["slot"] is not None and e["slot"].node_org_id == want:
            continue
        for sl in slots:
            if sl.node_org_id != want:
                continue
            verdict = gates.evaluate(shipment, e["vehicle"], e["window"], sl, now, params, vehicle_reserved=e["vehicle"].id in reserved_vehicles)
            if verdict.status == "PASS":
                e["slot"], e["verdict"] = sl, verdict
                break


def run_match(session: Session, actor: Actor, shipment: m.Shipment, now: datetime, node_org_id: uuid.UUID | None = None) -> dict:
    if actor.role not in RUN_ROLES:
        raise HTTPException(status_code=403, detail="Role cannot run matching")
    if shipment.status != "open":
        raise HTTPException(status_code=409, detail={"code": "SHIPMENT_NOT_OPEN",
                                                     "message": f"Shipment is '{shipment.status}'"})
    bk.expire_stale(session, now)  # tài nguyên hết hạn phải được trả về trước khi ghép
    aset = get_active(session)
    params = aset.params
    run_id = str(uuid.uuid4())

    locs = {l.id: l for l in session.execute(select(m.Location)).scalars()}
    vehicles = list(session.execute(select(m.Vehicle).order_by(m.Vehicle.plate)).scalars())
    windows = {}
    for w in session.execute(select(m.AvailabilityWindow).order_by(m.AvailabilityWindow.free_from)).scalars():
        windows[w.vehicle_id] = w  # cửa sổ muộn nhất ghi đè
    # lọc gần phù hợp: chỉ slot tại điểm đến của lô (slot sai điểm vẫn bị gate loại nếu lọt vào)
    slots = list(session.execute(select(m.Slot).where(m.Slot.location_id == shipment.dest_location_id)
                                 .order_by(m.Slot.start_at)).scalars())
    if node_org_id is not None:  # chủ hàng chỉ định ICD: chỉ xét slot của ICD đó (không có → báo rõ, không âm thầm đổi sang ICD khác)
        slots = [sl for sl in slots if sl.node_org_id == node_org_id]
        if not slots:
            raise HTTPException(status_code=422, detail={"code": "NODE_HAS_NO_SLOTS", "message": "The chosen ICD has no slots at this destination"})
    reserved_vehicles = set(session.execute(select(m.Reservation.resource_id).where(
        m.Reservation.resource_type == "vehicle", m.Reservation.status.in_(("held", "committed")))).scalars())

    passed, rejected, needs_data = [], [], []
    for veh in vehicles:
        win = windows.get(veh.id)
        best = None
        for slot in (slots or [None]):
            verdict = gates.evaluate(shipment, veh, win, slot, now, params, vehicle_reserved=veh.id in reserved_vehicles)
            if verdict.status == "PASS":
                best = (slot, verdict)
                break
            if best is None or len(verdict.rejections) < len(best[1].rejections):
                best = (slot, verdict)
        slot, verdict = best
        entry = {"vehicle": veh, "slot": slot, "verdict": verdict, "window": win}
        {"PASS": passed, "FAIL": rejected, "UNKNOWN": needs_data}[verdict.status].append(entry)

    def reasons(entry):
        return {"vehicle_id": str(entry["vehicle"].id), "plate": entry["vehicle"].plate,
                "status": entry["verdict"].status,
                "reasons": [bk.gate_to_dict(r) for r in entry["verdict"].rejections]}

    rejections = [reasons(e) for e in rejected]
    unknowns = [reasons(e) for e in needs_data]

    scored = []
    for e in passed:
        sc = score.score_candidate(shipment, e["vehicle"], _loc(locs, e["window"].location_id),
                                   _loc(locs, shipment.origin_location_id),
                                   gates.pickup_eta(e["window"], shipment, now, params), params)
        scored.append({**e, "scored": sc})
    scored.sort(key=score.rank_key)
    top = scored[: params.get("max_proposals", 3)]
    if node_org_id is None:
        _spread_icds(top, slots, shipment, now, params, reserved_vehicles)

    proposals = []
    ttl = timedelta(minutes=params.get("proposal_ttl_minutes", 15))
    for e in top:
        sc = e["scored"]
        prop = m.Proposal(
            shipment_id=shipment.id, vehicle_id=e["vehicle"].id, slot_id=e["slot"].id if e["slot"] else None,
            status="proposed", score=sc.score, score_components=sc.components,
            candidate_rejections=rejections + unknowns,
            input_snapshot={
                "run_id": run_id, "generated_at": now.isoformat(), "requested_by_org": str(actor.org_id),
                "shipment": {k: (v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, uuid.UUID) else v)
                             for k, v in {c.name: getattr(shipment, c.name) for c in m.Shipment.__table__.columns
                                          if c.name not in ("price_vnd", "customer_name")}.items()},  # không snapshot giá/khách
                "vehicle": {"id": str(e["vehicle"].id), "plate": e["vehicle"].plate,
                            "position_updated_at": e["vehicle"].position_updated_at.isoformat()
                            if e["vehicle"].position_updated_at else None},
                "gates": [bk.gate_to_dict(r) for r in e["verdict"].results],
                "eta": eta_mod.build(gates.pickup_eta(e["window"], shipment, now, params), now, params, shipment.cutoff_at),
                "estimated_saving_vnd": sc.estimated_saving_vnd, "deadhead_km": sc.deadhead_km,
                # Baseline chốt tại thời điểm ghép (trước khi biết kết quả) — DRAFT 11.1: không chọn baseline sau khi có kết quả
                "baseline": {"id": f"base-{run_id[:8]}", "empty_km": params["empty_km_baseline"],
                             "cost_per_km_vnd": params["cost_per_km_vnd"], "assumption_version": aset.version,
                             "fixed_at": now.isoformat(), "method": "static corridor baseline (assumption)"},
                "params_used": {k: params[k] for k in ("stale_position_minutes", "stale_shipment_minutes", "deadhead_minutes",
                                                       "transit_minutes", "handling_minutes", "score_weights")},
            },
            rule_version=params["rule_version"], model_version="rule-based", assumption_version=aset.version,
            expires_at=now + ttl,
        )
        session.add(prop)
        proposals.append(prop)
    session.flush()

    status = "proposals" if proposals else ("needs_data" if unknowns else "no_feasible_option")
    session.add(m.Event(
        tenant_id=actor.org_id, entity_type="shipment", entity_id=shipment.id, event_type="MATCH_RUN_COMPLETED",
        occurred_at=now, source_system="pivot.matching", source_event_id=run_id,
        payload={"run_id": run_id, "status": status, "proposals": [str(p.id) for p in proposals],
                 "rejections": rejections, "needs_data": unknowns, "rule_version": params["rule_version"],
                 "assumption_version": aset.version},
        correlation_id=run_id))
    return {"run_id": run_id, "status": status, "proposals": proposals, "rejections": rejections,
            "needs_data": unknowns, "rule_version": params["rule_version"], "assumption_version": aset.version,
            "generated_at": now, "evaluated_vehicles": len(vehicles), "eta_method": params.get("eta_method", "rule-based")}
