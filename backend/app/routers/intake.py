import base64
import binascii
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from ..auth import Actor, current_actor
from ..config import settings
from ..db import get_session
from ..intake.extractor import FIELDS, GeminiExtractor, build_extractor, build_image_extractor, image_guard, sniff_image
from ..intake.files import FileIntakeError, draft_from_file
from ..intake.service import build_draft

router = APIRouter(prefix="/v1/intake")


def client_ip(request: Request) -> str | None:
    """IP người gọi cho giới hạn lượt. Sau proxy (PIVOT_TRUST_PROXY=true, vd Render) lấy phần tử CUỐI của X-Forwarded-For — phần do proxy
    tự thêm; các phần phía trước do trình duyệt gửi nên có thể giả. Không sau proxy → IP kết nối trực tiếp."""
    if settings.trust_proxy:
        xff = request.headers.get("x-forwarded-for", "")
        last = xff.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else None


def _require_shipper(actor: Actor = Depends(current_actor)) -> None:
    """Chỉ chủ hàng tạo yêu cầu (CLAUDE.md 12/11, BUG-02) → chỉ chủ hàng dùng nhập liệu. Kiểm tra TRƯỚC khi giải mã/đọc tệp hay tính lượt Gemini
    (QA-03: nhà vận tải từng gọi được và tiêu lượt trên web công khai). Khai báo là dependency của route nên chạy trước validate body."""
    if actor.role != "shipper":
        raise HTTPException(status_code=403, detail="Only shippers can create requests")


def get_extractor(request: Request, actor: Actor = Depends(current_actor)):
    return build_extractor(settings, user_key=str(actor.user_id), ip=client_ip(request))


def get_image_extractor() -> GeminiExtractor | None:
    return build_image_extractor(settings)


def _audit_draft(session: Session, actor: Actor, draft: dict, now: datetime, extra: dict | None = None) -> None:
    # vết audit: KHÔNG lưu văn bản/ảnh/tệp gốc, chỉ băm + trích đoạn + trạng thái từng trường
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


def _decode(b64: str, code: str = "BAD_FILE", what: str = "The file") -> bytes:
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail={"code": code, "message": f"{what} is not valid base64"}) from None


def _file_draft(data: bytes, actor: Actor, session: Session, gemini: GeminiExtractor | None, extractor, ip: str | None) -> dict:
    """Chạy draft_from_file; bọc việc đọc ảnh bằng giới hạn lượt riêng (một tệp = một lượt, dù nhiều trang; lỗi phía mô hình → hoàn lượt)."""
    now = datetime.now(timezone.utc)
    guard, user = image_guard(settings), str(actor.user_id)
    used = {"n": 0}

    def read_images(images):
        reason = guard.acquire(user, now, ip)
        if reason:
            raise FileIntakeError(429, f"IMAGE_QUOTA_{reason.upper()}", "Image reading limit reached")
        used["n"] += 1
        got = gemini.extract_images(images, now, locs)
        if got is None:
            guard.refund(user, ip)  # người dùng không nhận được kết quả → không tính lượt
        return got

    locs = _locations(session)
    try:
        draft, audit = draft_from_file(data, now, locs, text_extractor=extractor, read_images=read_images if gemini else None,
                                       reader_name=gemini.name if gemini else "", cfg=settings)
    except FileIntakeError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message, **({"remaining": 0} if e.status == 429 else {})}) from None
    if used["n"]:
        draft["image_quota_remaining"] = guard.remaining(user, ip)
    _audit_draft(session, actor, draft, now, audit)
    session.commit()
    return draft


@router.post("/drafts/file", response_model=s.IntakeDraftOut, dependencies=[Depends(_require_shipper)])
def create_file_draft(body: s.IntakeFileIn, request: Request, actor: Actor = Depends(current_actor), session: Session = Depends(get_session),
                      gemini: GeminiExtractor | None = Depends(get_image_extractor), extractor=Depends(get_extractor)):
    """Tệp (PDF hoặc ảnh JPEG/PNG/WebP) → BẢN NHÁP. PDF có chữ đọc trong máy chủ (không cần khoá, không tính lượt ảnh);
    PDF scan và ảnh do Gemini đọc (giới hạn lượt ảnh), mọi trường "cần xem lại". Chưa tạo lô."""
    return _file_draft(_decode(body.file_base64), actor, session, gemini, extractor, client_ip(request))


@router.post("/drafts/image", response_model=s.IntakeDraftOut, dependencies=[Depends(_require_shipper)])
def create_image_draft(body: s.IntakeImageIn, request: Request, actor: Actor = Depends(current_actor), session: Session = Depends(get_session),
                       gemini: GeminiExtractor | None = Depends(get_image_extractor)):
    """Chỉ ảnh (giữ cho tương thích; giao diện dùng /drafts/file). Giới hạn riêng, mặc định 3 ảnh/người/ngày."""
    if gemini is None:
        raise HTTPException(status_code=501, detail={"code": "IMAGE_INTAKE_DISABLED", "message": "Image intake is not enabled on this server"})
    data = _decode(body.image_base64, "BAD_IMAGE", "image_base64")
    if len(data) > settings.intake_image_max_bytes:
        raise HTTPException(status_code=413, detail={"code": "IMAGE_TOO_LARGE", "message": f"Image must be at most {settings.intake_image_max_bytes // 1_000_000} MB"})
    if sniff_image(data) is None:
        raise HTTPException(status_code=415, detail={"code": "UNSUPPORTED_IMAGE", "message": "Only JPEG, PNG or WebP images are accepted"})
    return _file_draft(data, actor, session, gemini, None, client_ip(request))


@router.post("/drafts", response_model=s.IntakeDraftOut, dependencies=[Depends(_require_shipper)])
def create_draft(body: s.IntakeIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session),
                 extractor=Depends(get_extractor)):
    """Văn bản dán vào → BẢN NHÁP có trích đoạn nguồn từng trường. Chưa tạo lô; người dùng phải duyệt rồi mới tạo."""
    now = datetime.now(timezone.utc)
    locs = _locations(session)
    draft = build_draft(body.text, now, locs, extractor)
    _audit_draft(session, actor, draft, now)
    session.commit()
    return draft


__all__ = ["router", "FIELDS"]
