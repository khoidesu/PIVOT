import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from ..auth import Actor, current_actor
from ..config import settings
from ..db import get_session
from ..intake.extractor import FIELDS, build_extractor
from ..intake.service import build_draft

router = APIRouter(prefix="/v1/intake")


def get_extractor():
    return build_extractor(settings)


@router.post("/drafts", response_model=s.IntakeDraftOut)
def create_draft(body: s.IntakeIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session),
                 extractor=Depends(get_extractor)):
    """Văn bản dán vào → BẢN NHÁP có trích đoạn nguồn từng trường. Chưa tạo lô; người dùng phải duyệt rồi mới tạo."""
    if actor.role not in ("shipper", "carrier"):
        raise HTTPException(status_code=403, detail="Role cannot create requests")
    now = datetime.now(timezone.utc)
    locs = [{"id": str(l.id), "name": l.name, "kind": l.kind} for l in session.execute(select(m.Location)).scalars()]
    draft = build_draft(body.text, now, locs, extractor)
    # vết audit: KHÔNG lưu văn bản gốc, chỉ băm + trích đoạn + trạng thái từng trường
    session.add(m.Event(
        tenant_id=actor.org_id, entity_type="intake_draft", entity_id=uuid.UUID(draft["draft_id"]), event_type="INTAKE_DRAFT_CREATED",
        occurred_at=now, received_at=now, source_system="pivot.intake", source_event_id=draft["draft_id"],
        payload={"extractor": draft["extractor"], "source": draft["source"], "needs_review": draft["needs_review"],
                 "suspicious_instructions": draft["suspicious_instructions"],
                 "fields": {k: {"status": v["status"], "quote": (v["source"] or {}).get("quote")} for k, v in draft["fields"].items()
                            if k not in ("price_vnd", "customer_name")}},
        correlation_id=str(actor.user_id)))
    session.commit()
    return draft


__all__ = ["router", "FIELDS"]
