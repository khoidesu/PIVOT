"""Bảo vệ các thao tác PHÁ DỮ LIỆU demo khi triển khai công khai.

Đăng nhập demo là token dev (ai cũng chọn được vai trò). Khi `PIVOT_ADMIN_KEY` được đặt, reset / kịch bản demo / làm tuổi
dữ liệu / chạy worker thủ công ngoài vai điều phối viên còn cần header `X-Admin-Key` đúng. Không đặt (chạy local) → không yêu cầu.
"""
import hmac

from fastapi import Header, HTTPException

from .config import settings


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if not settings.admin_key:
        return
    if x_admin_key is None or not hmac.compare_digest(x_admin_key.encode(), settings.admin_key.encode()):
        raise HTTPException(status_code=403, detail={"code": "ADMIN_KEY_REQUIRED", "message": "Admin key required", "reasons": []})
