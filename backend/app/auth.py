"""Xác thực dev cho prototype local.

DRAFT bảng 2: dùng OIDC được quản lý, không tự xây mật khẩu. Prototype chạy local nên dùng token dev
`Authorization: Bearer dev:<user_key>` (vd dev:shipper_a), bật bằng PIVOT_ALLOW_DEV_TOKENS. Mọi API vẫn
kiểm tra tổ chức + quyền trên tài nguyên. Người dùng lấy khoá qua đăng nhập đơn giản `POST /v1/auth/login`
(tên + vai trò, không mật khẩu — chỉ dành cho demo); mỗi tab trình duyệt giữ khoá của riêng mình.
"""
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import settings
from .db import get_session


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID
    user_name: str
    org_id: uuid.UUID
    org_name: str
    org_type: str
    role: str  # shipper | carrier | node_operator | dispatcher


def actor_for_key(session: Session, key: str) -> Actor | None:
    row = session.execute(
        select(m.User, m.Membership, m.Organization)
        .join(m.Membership, m.Membership.user_id == m.User.id)
        .join(m.Organization, m.Organization.id == m.Membership.org_id)
        .where(m.User.email == f"{key}@demo.local")
        .order_by(m.Membership.id)  # user nhiều membership → luôn chọn cùng một membership (xác định)
    ).first()
    if row is None:
        return None
    user, membership, org = row
    return Actor(user.id, user.name, org.id, org.name, org.org_type, membership.role)


def current_actor(authorization: str | None = Header(default=None),
                  session: Session = Depends(get_session)) -> Actor:
    if not settings.allow_dev_tokens:
        raise HTTPException(status_code=401, detail="Dev tokens are disabled")
    if not authorization or not authorization.startswith("Bearer dev:"):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    actor = actor_for_key(session, authorization.removeprefix("Bearer dev:").strip())
    if actor is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return actor
