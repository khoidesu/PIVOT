"""Sandbox mô phỏng lợi ích của việc chọn xe điểm cao nhất. KHÔNG ghi DB, KHÔNG ghi `benefit_ledger` — tách hẳn khỏi lợi ích thật.

Khai báo TRƯỚC router lợi ích (`/benefits/{benefit_id}` sẽ nuốt `/benefits/sandbox/...` nếu đứng trước).
"""
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..assumptions import get_active
from ..auth import Actor, current_actor
from ..db import get_session
from ..sandbox import run_sandbox

router = APIRouter(prefix="/v1/benefits/sandbox")

DEFAULT = (100, 42)
_lock = threading.Lock()
_cache: dict[tuple, dict] = {}   # (n, seed, assumption_version) → kết quả (xác định nên cache an toàn)
_latest: dict[str, dict | None] = {"result": None}


class RunIn(BaseModel):
    n: int = Field(default=DEFAULT[0], ge=1, le=300)
    seed: int = Field(default=DEFAULT[1], ge=0, le=2**31 - 1)


def _run(session: Session, n: int, seed: int) -> dict:
    aset = get_active(session)
    key = (n, seed, aset.version)
    with _lock:
        hit = _cache.get(key)
        if hit is None:
            hit = run_sandbox(n, seed, params=aset.params, assumption_version=aset.version)
            _cache[key] = hit
            if len(_cache) > 20:  # trần bộ nhớ: bỏ kết quả cũ nhất
                _cache.pop(next(iter(_cache)))
        _latest["result"] = hit
        return hit


@router.post("/run")
def run(body: RunIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Chạy lại sandbox với (n, seed) — chỉ điều phối viên. Xác định: cùng (n, seed, giả định) → cùng kết quả."""
    if actor.role != "dispatcher":
        raise HTTPException(status_code=403, detail="Dispatcher only")
    return _run(session, body.n, body.seed)


@router.get("/latest")
def latest(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Kết quả lần chạy gần nhất (mọi vai trò xem được); chưa có thì chạy mặc định (100 ca, seed 42; vài trăm mili giây)."""
    with _lock:
        have = _latest["result"]
    return have if have is not None else _run(session, *DEFAULT)
