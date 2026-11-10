import uuid
from datetime import datetime, timezone

from tests.conftest import auth


def lot_id(client, user: str, code: str) -> str:
    return next(s["id"] for s in client.get("/v1/shipments", headers=auth(user)).json() if s["code"] == code)


def match(client, user: str, code: str) -> dict:
    sid = lot_id(client, user, code)
    r = client.post("/v1/match-runs", json={"shipment_id": sid}, headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()


def act(client, user: str, proposal: dict | str, action: str, key: str | None = None, version: int | None = None):
    pid = proposal["id"] if isinstance(proposal, dict) else proposal
    if version is None:
        version = proposal["version"] if isinstance(proposal, dict) else get(client, user, pid)["version"]
    return client.post(f"/v1/proposals/{pid}/{action}", json={"version": version},
                       headers={**auth(user), "Idempotency-Key": key or str(uuid.uuid4())})


def get(client, user: str, pid: str) -> dict:
    r = client.get(f"/v1/proposals/{pid}", headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()


def confirm_all(client, proposal: dict) -> dict:
    """hold (shipper_a) → carrier_b / shipper_a / node_c accept → confirmed. Dùng cho lô của A."""
    if proposal["status"] == "proposed":
        assert act(client, "shipper_a", proposal, "hold").status_code == 200
    for user in ("carrier_b", "shipper_a", "node_c"):
        r = act(client, user, proposal["id"], "accept")
        assert r.status_code == 200, r.text
    final = get(client, "shipper_a", proposal["id"])
    assert final["status"] == "confirmed"
    return final


def post_event(client, user: str, proposal_id: str, event_type: str, payload: dict | None = None,
               source_event_id: str | None = None, source_system: str = "carrier-tms"):
    return client.post("/v1/events", headers=auth(user), json={
        "entity_id": proposal_id, "event_type": event_type, "payload": payload or {},
        "occurred_at": datetime.now(timezone.utc).isoformat(), "source_system": source_system,
        "source_event_id": source_event_id or str(uuid.uuid4())})


def run_worker(client):
    r = client.post("/v1/demo/worker/run", headers=auth("dispatch"))
    assert r.status_code == 200, r.text
    return r.json()


def slot_remaining(slot_id: str) -> int:
    from sqlalchemy import select
    from app import models as m
    from app.db import SessionLocal
    with SessionLocal() as s:
        return s.execute(select(m.Slot.remaining).where(m.Slot.id == uuid.UUID(slot_id))).scalar_one()
