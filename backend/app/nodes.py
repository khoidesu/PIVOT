"""Duy trì nguồn cung SLOT MÔ PHỎNG của ICD (node) để dữ liệu mẫu không "tự chết" theo thời gian.

Vấn đề: slot mẫu được tạo MỘT lần (seed / lúc ICD đăng ký) nên sau vài giờ-vài ngày mọi slot đã qua → mọi xe bị `SLOT_WINDOW_MISSED`
và chủ hàng thấy "không có phương án khả thi" dù ICD không làm gì sai; `retime` lại bỏ qua dữ liệu của người tự đăng ký nên không cứu được.

Cách xử lý (chỉ cho slot MÔ PHỎNG `source="mock"`): kéo dài ĐUÔI lịch slot của ICD tới `slot_horizon_hours` kể từ bây giờ, khi nào có:
  (a) ICD đăng nhập, (b) ICD đang mở tab (định kỳ), (c) lúc chạy ghép (mọi ICD mô phỏng) — nên không phụ thuộc ai đang đăng nhập.
Nguyên tắc an toàn: không đụng slot đã có (kể cả slot đã qua — đề xuất/dock còn tham chiếu), không sửa `remaining` của slot đang được giữ,
KHÔNG nới hard gate (slot sinh ra vẫn bị gate cut-off/giờ xe tới/điểm đến như mọi slot), slot thật (`partner_api`/`manual_operator`) không bao giờ bị sinh.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .assumptions import get_active

DEFAULT_HORIZON_HOURS = 10   # lịch slot luôn phủ ít nhất tới đây (cấu hình `slot_horizon_hours` trong bộ giả định, nếu có)
SLOT_MINUTES = 30
LEAD_MINUTES = 30            # slot đầu tiên sinh ra bắt đầu sau bây giờ ít nhất chừng này
ROUND_MINUTES = 5


def _ceil(dt: datetime) -> datetime:
    q = ROUND_MINUTES * 60
    ts = int(dt.timestamp())
    return datetime.fromtimestamp(-(-ts // q) * q, tz=dt.tzinfo)


def refresh_slots(session: Session, org_id: uuid.UUID, now: datetime, horizon_hours: float | None = None) -> dict:
    """Kéo dài đuôi lịch slot mô phỏng của MỘT ICD. Idempotent; khoá dòng tổ chức nên hai lần gọi đồng thời không sinh trùng."""
    session.execute(select(m.Organization.id).where(m.Organization.id == org_id).with_for_update()).scalar_one_or_none()
    rows = session.execute(select(m.Slot).where(m.Slot.node_org_id == org_id).order_by(m.Slot.start_at)).scalars().all()
    if not rows:
        return {"created": 0, "reason": "NO_SLOTS"}
    if any(s.source != "mock" or not s.is_simulated for s in rows):  # có slot thật → nguồn cung không do mình sinh
        return {"created": 0, "reason": "NOT_SIMULATED"}
    horizon = timedelta(hours=horizon_hours if horizon_hours is not None else get_active(session).params.get("slot_horizon_hours", DEFAULT_HORIZON_HOURS))
    tail = max(s.end_at for s in rows)
    if tail >= now + horizon / 2:  # còn đủ dài → không sinh (tránh thêm slot mỗi lần gọi)
        return {"created": 0, "reason": "COVERED", "covered_until": tail.isoformat()}
    template = rows[-1]
    start = _ceil(max(tail, now + timedelta(minutes=LEAD_MINUTES)))
    created = 0
    while start + timedelta(minutes=SLOT_MINUTES) <= now + horizon:
        cap = 2 + int(start.timestamp() // (SLOT_MINUTES * 60)) % 3  # 2–4 chỗ, xác định theo giờ bắt đầu
        session.add(m.Slot(node_org_id=org_id, location_id=template.location_id, start_at=start, end_at=start + timedelta(minutes=SLOT_MINUTES),
                           capacity=cap, remaining=cap, source="mock", is_simulated=True))
        start += timedelta(minutes=SLOT_MINUTES)
        created += 1
    session.flush()
    return {"created": created, "reason": "EXTENDED", "covered_until": (start).isoformat()}


def ensure_supply(session: Session, now: datetime) -> int:
    """Gọi lúc ghép: mọi ICD có slot mô phỏng đều còn lịch phía trước. Trả tổng số slot mới. Duyệt theo id để không bế tắc khi hai lượt ghép chồng nhau."""
    org_ids = session.execute(select(m.Slot.node_org_id).where(m.Slot.source == "mock").distinct().order_by(m.Slot.node_org_id)).scalars().all()
    return sum(refresh_slots(session, o, now)["created"] for o in org_ids)
