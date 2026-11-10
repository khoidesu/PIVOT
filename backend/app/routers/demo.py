from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import models as m
from ..auth import Actor, current_actor
from ..config import settings
from ..db import get_session
from ..demo.scenarios import SCENARIOS, run_scenario

router = APIRouter(prefix="/v1/demo")


def _guard(actor: Actor) -> None:
    if settings.data_mode != "mock":
        raise HTTPException(status_code=403, detail="Only available for simulated (mock) data")
    if actor.role != "dispatcher":
        raise HTTPException(status_code=403, detail="Dispatcher only")


@router.post("/reset")
def reset(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Đưa toàn bộ dữ liệu MÔ PHỎNG về trạng thái seed chuẩn (xoá đề xuất, sự kiện, sổ lợi ích)."""
    _guard(actor)
    from ..seed import reset as do_reset, seed

    do_reset(session)
    info = seed(session)
    session.commit()
    return {"reset": True, **info}


@router.post("/age-positions")
def age_positions(minutes: int = 10, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Kịch bản 'dữ liệu quá hạn': lùi mốc cập nhật vị trí của mọi xe."""
    _guard(actor)
    minutes = max(1, min(minutes, 240))
    session.execute(update(m.Vehicle).where(m.Vehicle.position_updated_at.is_not(None))
                    .values(position_updated_at=m.Vehicle.position_updated_at - timedelta(minutes=minutes)))
    session.commit()
    return {"aged_minutes": minutes}


@router.get("/scenarios")
def list_scenarios(actor: Actor = Depends(current_actor)):
    return [{"id": sid} for sid, _ in SCENARIOS]


@router.post("/scenarios/{scenario_id}/run")
def run(scenario_id: str, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Chạy một kịch bản qua API thật (token dev của từng thành viên). Mỗi kịch bản tự reset nên lặp lại được."""
    _guard(actor)
    if scenario_id not in dict(SCENARIOS):
        raise HTTPException(status_code=404, detail="Unknown scenario")
    session.rollback()  # nhả giao dịch của request này: bước reset bên trong cần khoá TRUNCATE, nếu không sẽ tự chờ chính mình
    from fastapi.testclient import TestClient

    from ..main import app

    return run_scenario(scenario_id, lambda: TestClient(app))
