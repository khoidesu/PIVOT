"""Xác thực dev cho prototype local.

DRAFT bảng 2: dùng OIDC được quản lý, không tự xây mật khẩu. Prototype chạy local nên dùng token dev
`Authorization: Bearer dev:<user_key>` (vd dev:shipper_a), bật bằng PIVOT_ALLOW_DEV_TOKENS. Mọi API vẫn
kiểm tra tổ chức + quyền trên tài nguyên — bộ chọn vai trò trên UI chỉ là cách đổi token nhanh.
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


def current_actor(authorization: str | None = Header(default=None),
                  session: Session = Depends(get_session)) -> Actor:
    if not settings.allow_dev_tokens:
        raise HTTPException(status_code=401, detail="Dev tokens are disabled")
    if not authorization or not authorization.startswith("Bearer dev:"):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    key = authorization.removeprefix("Bearer dev:").strip()
    row = session.execute(
        select(m.User, m.Membership, m.Organization)
        .join(m.Membership, m.Membership.user_id == m.User.id)
        .join(m.Organization, m.Organization.id == m.Membership.org_id)
        .where(m.User.email == f"{key}@demo.local")
    ).first()
    if row is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    user, membership, org = row
    return Actor(user.id, user.name, org.id, org.name, org.org_type, membership.role)
