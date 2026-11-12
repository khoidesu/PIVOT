from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import fleet, nodes, schemas as s
from ..accounts import login_or_register
from ..auth import actor_for_key
from ..booking.service import BookingError
from ..config import settings
from ..db import get_session

router = APIRouter(prefix="/v1/auth")


class LoginIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(max_length=20)


class LoginOut(BaseModel):
    token: str  # dùng làm `Authorization: Bearer dev:<token>`
    is_new: bool
    me: s.MeOut


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, session: Session = Depends(get_session)):
    """Đăng nhập đơn giản (tên + vai trò, không mật khẩu): CHỈ cho dữ liệu mô phỏng."""
    if not settings.allow_dev_tokens or settings.data_mode != "mock":
        raise HTTPException(status_code=403, detail="Name-only login is disabled outside the simulated demo")
    try:
        key, is_new = login_or_register(session, body.name, body.role)
        session.commit()
    except BookingError as e:
        session.rollback()
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message, "reasons": []}) from None
    a = actor_for_key(session, key)
    if a.role == "carrier":  # nhà vận tải đăng nhập → xe rảnh được làm tươi vị trí/khung rảnh (lỗi ở đây không được chặn đăng nhập)
        try:
            fleet.refresh_fleet(session, a, datetime.now(timezone.utc))
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
            logging.getLogger(__name__).exception("fleet refresh on login failed")
    if a.role == "node_operator":  # ICD đăng nhập → lịch slot mô phỏng được kéo dài (lỗi không chặn đăng nhập)
        try:
            nodes.refresh_slots(session, a.org_id, datetime.now(timezone.utc))
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
            logging.getLogger(__name__).exception("slot refresh on login failed")
    return LoginOut(token=key, is_new=is_new, me=s.MeOut(user_id=a.user_id, user_name=a.user_name, org_id=a.org_id,
                                                         org_name=a.org_name, org_type=a.org_type, role=a.role))
