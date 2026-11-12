import base64
import binascii
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
from ..intake.extractor import (FIELDS, GeminiExtractor, RuleExtractor, StaticExtractor, build_extractor, image_guard, sniff_image,
                                strip_jpeg_metadata)
from ..intake.service import build_draft, mark_image_draft

router = APIRouter(prefix="/v1/intake")


def get_extractor(actor: Actor = Depends(current_actor)):
    return build_extractor(settings, user_key=str(actor.user_id))


def get_image_extractor() -> GeminiExtractor | None:
    if not (settings.gemini_api_key and settings.intake_image_enabled):
        return None
    return GeminiExtractor(settings.gemini_api_key, settings.gemini_model, settings.gemini_url, timeout=max(settings.gemini_timeout_s, 30.0))


def _audit_draft(session: Session, actor: Actor, draft: dict, now: datetime, extra: dict | None = None) -> None:
    # vết audit: KHÔNG lưu văn bản/ảnh gốc, chỉ băm + trích đoạn + trạng thái từng trường
    session.add(m.Event(
        tenant_id=actor.org_id, entity_type="intake_draft", entity_id=uuid.UUID(draft["draft_id"]), event_type="INTAKE_DRAFT_CREATED",
        occurred_at=now, received_at=now, source_system="pivot.intake", source_event_id=draft["draft_id"],
        payload={"extractor": draft["extractor"], "source": draft["source"], "needs_review": draft["needs_review"],
                 "suspicious_instructions": draft["suspicious_instructions"],
                 "fields": {k: {"status": v["status"], "quote": (v["source"] or {}).get("quote")} for k, v in draft["fields"].items()
                            if k not in ("price_vnd", "customer_name")}, **(extra or {})},
        correlation_id=str(actor.user_id)))


def _locations(session: Session) -> list[dict]:
    return [{"id": str(l.id), "name": l.name, "kind": l.kind} for l in session.execute(select(m.Location)).scalars()]


@router.post("/drafts/image", response_model=s.IntakeDraftOut)
def create_image_draft(body: s.IntakeImageIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session),
                       gemini: GeminiExtractor | None = Depends(get_image_extractor)):
    """Ảnh (phiếu, tin nhắn chụp) → Gemini đọc → BẢN NHÁP kèm bản phiên âm. Mọi trường từ ảnh đều ở trạng thái "cần xem lại".
    Giới hạn riêng (mặc định 3 ảnh/người/ngày); không có bộ luật để quay về nên hết lượt/lỗi là báo lỗi rõ, không tạo bản nháp trống."""
    if actor.role not in ("shipper", "carrier"):
        raise HTTPException(status_code=403, detail="Role cannot create requests")
    if gemini is None:
        raise HTTPException(status_code=501, detail={"code": "IMAGE_INTAKE_DISABLED", "message": "Image intake is not enabled on this server"})
    try:
        data = base64.b64decode(body.image_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail={"code": "BAD_IMAGE", "message": "image_base64 is not valid base64"}) from None
    if len(data) > settings.intake_image_max_bytes:
        raise HTTPException(status_code=413, detail={"code": "IMAGE_TOO_LARGE", "message": f"Image must be at most {settings.intake_image_max_bytes // 1_000_000} MB"})
    mime = sniff_image(data)  # loại ảnh theo NỘI DUNG, không tin khai báo của khách
    if mime is None:
        raise HTTPException(status_code=415, detail={"code": "UNSUPPORTED_IMAGE", "message": "Only JPEG, PNG or WebP images are accepted"})
    data = strip_jpeg_metadata(data)  # bỏ EXIF (có thể chứa toạ độ GPS) trước khi gửi ra ngoài
    now = datetime.now(timezone.utc)
    guard, user = image_guard(settings), str(actor.user_id)
    reason = guard.acquire(user, now)
    if reason:
        raise HTTPException(status_code=429, detail={"code": f"IMAGE_QUOTA_{reason.upper()}", "message": "Image reading limit reached", "remaining": 0})
    locs = _locations(session)
    got = gemini.extract_image(data, mime, now, locs)
    if got is None:
        guard.refund(user)  # người dùng không nhận được kết quả → không tính lượt
        raise HTTPException(status_code=503, detail={"code": "IMAGE_UNREADABLE", "message": "The image could not be read. Try a sharper photo or try again later"})
    fields, transcript = got
    # Gemini có lúc bỏ sót trường (kết quả đọc ảnh dao động giữa các lần): trường còn trống thì thử bộ luật trên BẢN PHIÊN ÂM
    for k, v in RuleExtractor().extract(transcript, now, locs).items():
        if k in FIELDS and (fields.get(k) or {}).get("value") is None and v.get("value") is not None:
            fields[k] = v
    draft = mark_image_draft(build_draft(transcript, now, locs, StaticExtractor(gemini.name, fields)), mime, transcript)
    draft["image_quota_remaining"] = guard.remaining(user)
    _audit_draft(session, actor, draft, now, {"image": {"mime": mime, "bytes": len(data)}})
    session.commit()
    return draft


@router.post("/drafts", response_model=s.IntakeDraftOut)
def create_draft(body: s.IntakeIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session),
                 extractor=Depends(get_extractor)):
    """Văn bản dán vào → BẢN NHÁP có trích đoạn nguồn từng trường. Chưa tạo lô; người dùng phải duyệt rồi mới tạo."""
    if actor.role not in ("shipper", "carrier"):
        raise HTTPException(status_code=403, detail="Role cannot create requests")
    now = datetime.now(timezone.utc)
    locs = _locations(session)
    draft = build_draft(body.text, now, locs, extractor)
    _audit_draft(session, actor, draft, now)
    session.commit()
    return draft


__all__ = ["router", "FIELDS"]
