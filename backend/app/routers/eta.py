from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.orm import Session

from ..admin import require_admin
from ..assumptions import get_active
from ..auth import Actor, current_actor
from ..db import get_session
from ..eta import compare, ml, onnx_model, sandbox

router = APIRouter(prefix="/v1/eta")


class TrainIn(BaseModel):
    drift: float = Field(default=ml.DEFAULT_DRIFT, ge=0.0, le=1.0)  # độ "trôi" mô phỏng ở đoạn cuối; lớn → mô hình bị hạ về luật


class PredictIn(BaseModel):
    depart_at: AwareDatetime
    km: float = Field(default=ml.BASE_KM, gt=0, le=200)
    # tuỳ chọn, chỉ dùng cho model ONNX; bỏ trống → mặc định (KCN_A_ICD, medium, trời khô) và ghi vào `assumed` của kết quả
    route_id: Literal["KCN_A_ICD", "KCN_B_ICD"] | None = None
    vehicle_class: Literal["heavy", "medium", "light"] | None = None
    rain_mm_h: float | None = Field(default=None, ge=0, le=30)
    wind_kmh: float | None = Field(default=None, ge=0, le=60)


@router.get("/model")
def model(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    ml.ensure_trained(get_active(session).params["transit_minutes"])
    return {**ml.model_info(), "rule_version": get_active(session).params["eta"]["model_version"]}


@router.post("/train", dependencies=[Depends(require_admin)])
def train(body: TrainIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    if actor.role != "dispatcher":
        raise HTTPException(status_code=403, detail="Dispatcher only")
    if onnx_model.available():  # model ONNX huấn luyện NGOÀI là nguồn chính thức: huấn luyện lại trong app chỉ đụng mô hình mô phỏng không dùng → từ chối rõ ràng
        raise HTTPException(status_code=409, detail={"code": "ONNX_MODEL_IN_USE", "message": "The ONNX model is trained outside the app; use the ETA sandbox drift sweep or retrain with the notebook"})
    return ml.train(get_active(session).params["transit_minutes"], body.drift)


@router.post("/predict")
def predict(body: PredictIn, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """What-if: ETA luật (có P50/P90 theo khung giờ) và ETA ML (nếu đã promote); `used` cho biết bên nào đang được dùng."""
    ctx = {k: v for k in ("route_id", "vehicle_class", "rain_mm_h", "wind_kmh") if (v := getattr(body, k)) is not None}
    return compare.rule_vs_ml(get_active(session).params, body.depart_at, body.km, ctx)


# ---------------------------------------------------------------- ETA Sandbox (công cụ nội bộ để thử/tinh chỉnh trước khi chốt demo)
def _sandbox_guard(actor: Actor) -> None:
    if actor.role != "dispatcher":
        raise HTTPException(status_code=403, detail="Dispatcher only")


@router.get("/sandbox/drift-sweep", dependencies=[Depends(require_admin)])
def sandbox_drift_sweep(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Huấn luyện lại theo nhiều độ trôi để thấy ngưỡng mô hình tự hạ về luật. Trạng thái mô hình hiện tại được khôi phục sau khi chạy."""
    _sandbox_guard(actor)
    return sandbox.sweep_drift(params=get_active(session).params)


@router.get("/sandbox/scenarios", dependencies=[Depends(require_admin)])
def sandbox_scenarios(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """So sánh P50/P90 của ETA luật và ETA ML theo từng khung giờ."""
    _sandbox_guard(actor)
    return sandbox.scenario_matrix(get_active(session).params)


@router.get("/sandbox/signals-health", dependencies=[Depends(require_admin)])
def sandbox_signals_health(fresh: bool = False, actor: Actor = Depends(current_actor)):
    """Gọi thử OSRM / Open-Meteo / Mapbox với điểm mẫu. fresh=true bỏ qua cache (tốn thêm hạn mức API)."""
    _sandbox_guard(actor)
    return sandbox.signals_health_check(fresh=fresh)
