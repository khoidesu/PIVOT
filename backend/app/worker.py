"""Worker đọc outbox_jobs trong PostgreSQL (DRAFT bảng 2): lease/lock, retry có giới hạn, bảng lỗi + replay.

- Claim bằng SELECT … FOR UPDATE SKIP LOCKED + lease (locked_until) → nhiều worker không tranh cùng job.
- Tác động nghiệp vụ và việc đánh dấu `done` nằm trong CÙNG transaction → worker chết giữa chừng thì không có tác động
  nào được lưu, hết lease sẽ được xử lý lại (at-least-once, consumer idempotent — không hứa exactly-once).
- Quá MAX_ATTEMPTS → status='failed' (xem /v1/outbox); replay đưa về pending.

Chạy: `python -m app.worker` (vòng lặp) hoặc app FastAPI tự chạy nền khi PIVOT_WORKER_INLINE=true.
"""
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from . import models as m
from .db import SessionLocal
from .booking.service import expire_stale
from .events import service as events

log = logging.getLogger("pivot.worker")
MAX_ATTEMPTS = 5
LEASE_SECONDS = 30


def _handle(session: Session, job: m.OutboxJob, now: datetime) -> None:
    if job.topic == "event.apply":
        events.apply_event(session, uuid.UUID(job.payload["event_id"]), now)
    elif job.topic == "proposal.confirmed":
        # Node dùng nguồn mock/manual: không có API ngoài để gọi. Với partner_api, đây là chỗ gọi qua
        # idempotency key + đối soát, và chỉ hiển thị confirmed_external sau khi đối tác trả lời (DRAFT 5.4).
        log.info("proposal.confirmed %s (mock confirmation, no external call)", job.payload.get("proposal_id"))
    else:
        raise ValueError(f"unknown topic {job.topic}")


def maintenance(factory: sessionmaker = SessionLocal, now: datetime | None = None) -> None:
    """Các việc dọn nền: hold/đề xuất quá hạn (trả slot — GET không ghi DB), NO_SHOW + hàng đợi dock, leo thang quá SLA + dữ liệu
    vị trí quá cũ. Mỗi việc một transaction riêng và lỗi của việc này KHÔNG làm hỏng việc khác hay cả vòng xử lý job outbox."""
    from .docks.service import sweep as dock_sweep
    from .incidents.service import sweep
    for name, step in (("expire_stale", expire_stale), ("dock_sweep", dock_sweep), ("sweep", sweep)):
        try:
            with factory() as s:
                step(s, now or datetime.now(timezone.utc))
                s.commit()
        except Exception:  # noqa: BLE001 — việc dọn lỗi (DB chập chờn, dữ liệu bất thường) chỉ được ghi log, không dừng worker
            log.exception("worker maintenance step failed: %s", name)


def process_pending(factory: sessionmaker = SessionLocal, limit: int = 50, now: datetime | None = None,
                    fail_hook=None) -> dict:
    """Xử lý tối đa `limit` job đến hạn. fail_hook(job) chỉ dùng để test sự cố worker chết giữa chừng."""
    stats = {"done": 0, "retry": 0, "failed": 0}
    maintenance(factory, now)
    for _ in range(limit):
        now_ = now or datetime.now(timezone.utc)
        with factory() as s:  # tx1: claim
            job = s.execute(select(m.OutboxJob).where(
                m.OutboxJob.status == "pending",
                or_(m.OutboxJob.locked_until.is_(None), m.OutboxJob.locked_until < now_),
            ).order_by(m.OutboxJob.created_at).limit(1).with_for_update(skip_locked=True)).scalar_one_or_none()
            if job is None:
                break
            job.locked_until = now_ + timedelta(seconds=LEASE_SECONDS)
            job.attempts += 1
            job_id = job.id
            s.commit()
        try:
            with factory() as s:  # tx2: tác động + done, nguyên tử
                job = s.get(m.OutboxJob, job_id)
                _handle(s, job, now_)
                if fail_hook:
                    fail_hook(job)
                job.status = "done"
                job.locked_until = None
                s.commit()
            stats["done"] += 1
        except Exception as exc:  # noqa: BLE001
            with factory() as s:  # tx3: ghi lỗi + backoff
                job = s.get(m.OutboxJob, job_id)
                job.last_error = f"{type(exc).__name__}: {exc}"[:500]
                if job.attempts >= MAX_ATTEMPTS:
                    job.status = "failed"
                    stats["failed"] += 1
                else:
                    job.locked_until = now_ + timedelta(seconds=min(2 ** job.attempts, 30))
                    stats["retry"] += 1
                s.commit()
    return stats


def replay(session: Session, job_id: uuid.UUID) -> m.OutboxJob | None:
    job = session.get(m.OutboxJob, job_id)
    if job is not None and job.status == "failed":
        job.status, job.attempts, job.locked_until, job.last_error = "pending", 0, None, None
    return job


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    log.info("worker started")
    while True:
        try:
            process_pending()
        except Exception:  # noqa: BLE001 — mất kết nối DB tạm thời không được làm worker chết hẳn
            log.exception("worker iteration failed")
        time.sleep(1)


if __name__ == "__main__":
    main()
