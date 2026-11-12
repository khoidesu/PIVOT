"""Dựng ProposalOut: chỉ hiển thị dữ liệu 'đủ dùng' (không có giá/khách hàng; đội xe của tổ chức khác được che)
+ nút hành động theo quyền thật. Dựng THEO LÔ (vài truy vấn cho cả danh sách, không N+1) và KHÔNG ghi DB khi đọc."""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import Actor
from ..matching.redact import redact_rejections
from . import service as bk


def effective_status(prop: m.Proposal, now: datetime) -> str:
    """Hiển thị 'expired' ngay khi quá hạn dù worker chưa kịp ghi (GET không ghi DB; worker dọn trong ≤1 giây)."""
    if prop.status in bk.OPEN_STATES and prop.expires_at is not None and prop.expires_at < now:
        return "expired"
    return prop.status


def proposal_views(session: Session, actor: Actor, props: list[m.Proposal], now: datetime) -> list[dict]:
    if not props:
        return []
    ships = {x.id: x for x in session.execute(select(m.Shipment).where(m.Shipment.id.in_({p.shipment_id for p in props}))).scalars()}
    vehs = {x.id: x for x in session.execute(select(m.Vehicle).where(m.Vehicle.id.in_({p.vehicle_id for p in props}))).scalars()}
    slot_ids = {p.slot_id for p in props if p.slot_id}
    slots = {x.id: x for x in session.execute(select(m.Slot).where(m.Slot.id.in_(slot_ids))).scalars()} if slot_ids else {}
    accepted = defaultdict(set)
    for pid, party in session.execute(select(m.Decision.proposal_id, m.Decision.party).where(
            m.Decision.proposal_id.in_([p.id for p in props]), m.Decision.action == "accept")):
        if party:
            accepted[pid].add(party)
    # tên tổ chức + chủ của các xe bị loại (để che chi tiết đội xe của tổ chức khác)
    rej_vids = {r["vehicle_id"] for p in props for r in (p.candidate_rejections or [])}
    veh_org = {str(v.id): v.tenant_id for v in session.execute(select(m.Vehicle).where(
        m.Vehicle.id.in_(rej_vids))).scalars()} if rej_vids else {}
    org_ids = {v.tenant_id for v in vehs.values()} | {s.tenant_id for s in ships.values()} | {s.node_org_id for s in slots.values()}
    names = {o.id: o.name for o in session.execute(select(m.Organization).where(m.Organization.id.in_(org_ids))).scalars()}

    out = []
    for prop in props:
        ship, veh = ships[prop.shipment_id], vehs[prop.vehicle_id]
        slot = slots.get(prop.slot_id) if prop.slot_id else None
        orgs = bk.party_orgs(ship, veh, slot)
        done, mine = accepted[prop.id], bk.actor_parties(actor, orgs)
        status = effective_status(prop, now)
        open_state = status in bk.OPEN_STATES
        seconds_left = max(int((prop.expires_at - now).total_seconds()), 0) if status == "pending_acceptance" and prop.expires_at else None
        snap = prop.input_snapshot or {}
        out.append({
            "id": prop.id, "status": status, "version": prop.version, "is_simulated": True,
            "confirmation_source": slot.source if slot else None,  # mock | manual_operator | partner_api
            "shipment": {k: getattr(ship, k) for k in (
                "id", "code", "cargo_type", "weight_kg", "volume_m3", "ready_at", "pickup_deadline", "cutoff_at",
                "origin_location_id", "dest_location_id", "status")},
            "vehicle": {"id": veh.id, "plate": veh.plate, "capacity_kg": veh.capacity_kg, "capacity_m3": veh.capacity_m3,
                        "carrier_org_name": names.get(orgs["carrier"]), "yard": (snap.get("vehicle") or {}).get("yard_name")},
            "slot": None if slot is None else {
                "id": slot.id, "start_at": slot.start_at, "end_at": slot.end_at, "remaining": slot.remaining,
                "capacity": slot.capacity, "source": slot.source, "node_org_name": names.get(orgs.get("node"))},
            "score": prop.score, "score_components": prop.score_components,
            "estimated_saving_vnd": snap.get("estimated_saving_vnd"), "deadhead_km": snap.get("deadhead_km"),
            "eta": snap.get("eta"), "gates": snap.get("gates", []),
            "rejections": redact_rejections(prop.candidate_rejections, veh_org, actor),
            "rule_version": prop.rule_version, "model_version": prop.model_version, "assumption_version": prop.assumption_version,
            "expires_at": prop.expires_at, "hold_seconds_left": seconds_left,
            "parties": {p: {"org_name": names.get(orgs.get(p)), "accepted": p in done} for p in bk.PARTIES if p in orgs},
            "my_actions": {
                "hold": status == "proposed" and bk.can_hold(actor, orgs),
                "accept": status == "pending_acceptance" and bool(mine - done),
                "reject": open_state and (bool(mine) or bk.can_hold(actor, orgs)),
            },
            "run_id": snap.get("run_id"), "created_at": prop.created_at,
        })
    return out


def proposal_view(session: Session, actor: Actor, prop: m.Proposal, now: datetime) -> dict:
    return proposal_views(session, actor, [prop], now)[0]
