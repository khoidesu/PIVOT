"""Timeline, replay và xử lý ngoại lệ (DRAFT mục 6/Ngày 4)."""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import Actor
from . import service as bk

RESOLUTIONS = ("accept_delay", "request_replan")


def load_visible(session: Session, actor: Actor, proposal_id: uuid.UUID):
    prop = session.get(m.Proposal, proposal_id)
    if prop is None:
        raise bk.BookingError("NOT_FOUND", "Proposal not found", 404)
    ship, veh = session.get(m.Shipment, prop.shipment_id), session.get(m.Vehicle, prop.vehicle_id)
    slot = session.get(m.Slot, prop.slot_id) if prop.slot_id else None
    orgs = bk.party_orgs(ship, veh, slot)
    if not bk.is_visible(actor, orgs):
        raise bk.BookingError("NOT_FOUND", "Proposal not found", 404)
    return prop, ship, veh, slot, orgs


def _benefit_time(session: Session, b: m.BenefitLedger):
    """Thời điểm ghi sổ = thời điểm của sự kiện bằng chứng (TRIP_COMPLETED)."""
    for ref in b.evidence_refs or []:
        if ref.get("type") == "event":
            ev = session.get(m.Event, uuid.UUID(ref["id"]))
            if ev:
                return ev.received_at
    return None


def timeline(session: Session, actor: Actor, proposal_id: uuid.UUID) -> dict:
    prop, ship, _veh, _slot, orgs = load_visible(session, actor, proposal_id)
    names = {o.id: o.name for o in session.execute(select(m.Organization)).scalars()}
    items: list[dict] = []

    for ev in session.execute(select(m.Event).where(
            m.Event.entity_type == "shipment", m.Event.entity_id == ship.id,
            m.Event.event_type == "MATCH_RUN_COMPLETED")).scalars():
        if str(prop.id) in (ev.payload or {}).get("proposals", []):
            items.append({"at": ev.occurred_at, "kind": "match", "code": ev.event_type, "actor": names.get(ev.tenant_id),
                          "quality": ev.quality_status, "latency_s": None,
                          "detail": {"run_id": ev.payload.get("run_id"), "rule_version": ev.payload.get("rule_version"),
                                     "rejected": len(ev.payload.get("rejections", []))}})
    for d in session.execute(select(m.Decision).where(m.Decision.proposal_id == prop.id)).scalars():
        user = session.get(m.User, d.actor_user_id)
        items.append({"at": d.at, "kind": "decision", "code": d.action, "actor": f"{user.name if user else '?'} · {names.get(d.actor_org_id)}",
                      "quality": None, "latency_s": None, "detail": {"party": d.party, "version": d.proposal_version}})
    for ev in session.execute(select(m.Event).where(m.Event.entity_type == "proposal", m.Event.entity_id == prop.id)).scalars():
        items.append({"at": ev.occurred_at, "kind": "event", "code": ev.event_type, "actor": f"{ev.source_system} · {names.get(ev.tenant_id)}",
                      "quality": ev.quality_status,
                      "latency_s": int((ev.received_at - ev.occurred_at).total_seconds()) if ev.received_at else None,
                      "detail": {"payload": ev.payload, "source_event_id": ev.source_event_id}})
    for ex in session.execute(select(m.ExceptionRecord).where(m.ExceptionRecord.proposal_id == prop.id)).scalars():
        items.append({"at": ex.created_at, "kind": "exception", "code": ex.exc_type, "actor": None, "quality": ex.status,
                      "latency_s": None, "detail": {"exception_id": str(ex.id), **(ex.detail or {})}})
    for b in session.execute(select(m.BenefitLedger).where(m.BenefitLedger.proposal_id == prop.id)).scalars():
        items.append({"at": b.verified_at or _benefit_time(session, b), "kind": "benefit",
                      "code": f"BENEFIT_{b.status.upper()}", "actor": b.verifier, "quality": b.status, "latency_s": None,
                      "detail": {"benefit_id": str(b.id)}})
    items = [i for i in items if i["at"] is not None]
    items.sort(key=lambda i: i["at"])
    return {"proposal_id": prop.id, "status": prop.status, "version": prop.version, "shipment_code": ship.code,
            "items": items}


def replay(session: Session, actor: Actor, proposal_id: uuid.UUID) -> dict:
    """Tái lập quyết định từ dữ liệu ĐÃ LƯU (không dùng dữ liệu hiện tại): điểm tính lại từ thành phần + trọng số đã lưu."""
    prop, *_ = load_visible(session, actor, proposal_id)
    c = prop.score_components or {}
    w = c.get("weights") or {}
    recomputed = round(sum(w.get(k, 0) * c.get(k, 0) for k in ("fit", "time_margin", "empty_km_saved")), 6)
    gates = (prop.input_snapshot or {}).get("gates", [])
    return {
        "proposal_id": prop.id, "stored_score": prop.score, "recomputed_score": recomputed,
        "reproducible": prop.score is not None and abs(prop.score - recomputed) < 1e-6,
        "weights_sum": round(sum(w.values()), 9) if w else None,
        "all_gates_pass": bool(gates) and all(g["status"] == "PASS" for g in gates),
        "gate_count": len(gates), "rejected_candidates": len(prop.candidate_rejections or []),
        "rule_version": prop.rule_version, "model_version": prop.model_version,
        "assumption_version": prop.assumption_version, "run_id": (prop.input_snapshot or {}).get("run_id"),
        "baseline": (prop.input_snapshot or {}).get("baseline"),
        "snapshot_keys": sorted((prop.input_snapshot or {}).keys()),
    }


def resolve_exception(session: Session, actor: Actor, exception_id: uuid.UUID, resolution: str, note: str | None,
                      now: datetime) -> m.ExceptionRecord:
    """Ngoại lệ do bên liên quan quyết định. KHÔNG tự sửa/chuyển xe của chuyến đã cam kết (DRAFT 5.4)."""
    if resolution not in RESOLUTIONS:
        raise bk.BookingError("VALIDATION", f"resolution must be one of {RESOLUTIONS}", 422)
    ex = session.execute(select(m.ExceptionRecord).where(m.ExceptionRecord.id == exception_id).with_for_update()).scalar_one_or_none()
    if ex is None:
        raise bk.BookingError("NOT_FOUND", "Exception not found", 404)
    prop, _ship, _veh, _slot, orgs = load_visible(session, actor, ex.proposal_id)
    if actor.role not in ("shipper", "carrier") or actor.org_id not in (orgs.get("shipper"), orgs.get("carrier")):
        raise bk.BookingError("FORBIDDEN", "Only the shipper or carrier of this trip can decide", 403)
    if ex.status == "resolved":
        return ex  # idempotent
    ex.status = "resolved"
    ex.detail = {**(ex.detail or {}), "resolution": resolution, "note": note, "resolved_by": actor.user_name,
                 "resolved_org": actor.org_name, "resolved_at": now.isoformat()}
    session.add(m.Decision(proposal_id=prop.id, actor_user_id=actor.user_id, actor_org_id=actor.org_id,
                           action="resolve_exception", party=None, proposal_version=prop.version))
    session.flush()
    return ex
