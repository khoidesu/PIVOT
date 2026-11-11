from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.orm import Session

from ..admin import require_admin
from ..assumptions import get_active
from ..auth import Actor, current_actor
from ..db import get_session
from ..eta import baseline, ml

router = APIRouter(prefix="/v1/eta")


class TrainIn(BaseModel):
    drift: float = Field(default=ml.DEFAULT_DRIFT, ge=0.0, le=1.0)  # độ "trôi" mô phỏng ở đoạn cuối; lớn → mô hình bị hạ về luật


class PredictIn(BaseModel):
    depart_at: AwareDatetime
    km: float = Field(default=ml.BASE_KM, gt=0, le=200)


@router.get("/model")
def model(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    ml.ensure_trained(get_active(session).params["transit_minutes"])
    return {**ml.model_info(), "rule_version": get_active(session).params["eta"]["model_version"]}


@router.post("/train", dependencies=[Depends(require_admin)])
def train(body: TrainIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    if actor.role != "dispatcher":
        raise HTTPException(status_code=403, detail="Dispatcher only")
    return ml.train(get_active(session).params["transit_minutes"], body.drift)


@router.post("/predict")
def predict(body: PredictIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """What-if: ETA luật (có P50/P90 theo khung giờ) và ETA ML (nếu đã promote); `used` cho biết bên nào đang được dùng."""
    params = get_active(session).params
    ml.ensure_trained(params["transit_minutes"])
    base = params["transit_minutes"] * (body.km / ml.BASE_KM)
    p50 = body.depart_at + timedelta(minutes=base)
    rule = baseline.interval(p50, base, body.depart_at, params)
    pred = ml.predict(body.depart_at, body.km)
    return {"rule": {**rule, "minutes_p50": round(base), "method": "rule-based", "confidence": "low (rule-based)"}, "ml": pred,
            "used": "ml" if pred else "rule", "status": ml.model_info()["status"], "is_simulated": True}
