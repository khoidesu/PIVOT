from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m


def get_active(session: Session) -> m.AssumptionSet:
    """Bộ giả định đang hiệu lực (cờ is_active tường minh). Thiếu → 503, không để lộ 500."""
    rows = session.execute(select(m.AssumptionSet).where(m.AssumptionSet.is_active.is_(True))).scalars().all()
    if len(rows) != 1:
        raise HTTPException(status_code=503, detail="No single active assumption set — run the seed")
    return rows[0]
