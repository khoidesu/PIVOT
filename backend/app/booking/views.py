"""Dựng ProposalOut: chỉ hiển thị dữ liệu 'đủ dùng' (không có giá/khách hàng) + nút hành động theo quyền thật."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import Actor
from . import service as bk


def proposal_view(session: Session, actor: Actor, prop: m.Proposal, now: datetime) -> dict:
    ship = session.get(m.Shipment, prop.shipment_id)
    veh = session.get(m.Vehicle, prop.vehicle_id)
    slot = session.get(m.Slot, prop.slot_id) if prop.slot_id else None
    orgs = bk.party_orgs(ship, veh, slot)
    names = {o.id: o.name for o in session.execute(
        select(m.Organization).where(m.Organization.id.in_(set(orgs.values())))).scalars()}
    done = bk.accepted_parties(session, prop.id)
    mine = bk.actor_parties(actor, orgs)
    open_state = prop.status in bk.OPEN_STATES
    seconds_left = None
    if prop.status == "pending_acceptance" and prop.expires_at:
        seconds_left = max(int((prop.expires_at - now).total_seconds()), 0)

    actions = {
        "hold": prop.status == "proposed" and bk.can_hold(actor, orgs),
        "accept": prop.status == "pending_acceptance" and bool(mine - done),
        "reject": open_state and (bool(mine) or bk.can_hold(actor, orgs)),
    }
    snap = prop.input_snapshot or {}
    return {
        "id": prop.id,
        "status": prop.status,
        "version": prop.version,
        "is_simulated": True,
        "confirmation_source": slot.source if slot else None,  # mock | manual_operator | partner_api
        "shipment": {k: getattr(ship, k) for k in (
            "id", "code", "cargo_type", "weight_kg", "volume_m3", "ready_at", "pickup_deadline", "cutoff_at",
            "origin_location_id", "dest_location_id", "status")},
        "vehicle": {"id": veh.id, "plate": veh.plate, "capacity_kg": veh.capacity_kg, "capacity_m3": veh.capacity_m3,
                    "carrier_org_name": names.get(orgs["carrier"])},
        "slot": None if slot is None else {
            "id": slot.id, "start_at": slot.start_at, "end_at": slot.end_at, "remaining": slot.remaining,
            "capacity": slot.capacity, "source": slot.source, "node_org_name": names.get(orgs.get("node"))},
        "score": prop.score,
        "score_components": prop.score_components,
        "estimated_saving_vnd": snap.get("estimated_saving_vnd"),
        "deadhead_km": snap.get("deadhead_km"),
        "eta": snap.get("eta"),
        "gates": snap.get("gates", []),
        "rejections": prop.candidate_rejections,
        "rule_version": prop.rule_version,
        "model_version": prop.model_version,
        "assumption_version": prop.assumption_version,
        "expires_at": prop.expires_at,
        "hold_seconds_left": seconds_left,
        "parties": {p: {"org_name": names.get(orgs.get(p)), "accepted": p in done} for p in bk.PARTIES if p in orgs},
        "my_actions": actions,
        "run_id": snap.get("run_id"),
        "created_at": prop.created_at,
    }
