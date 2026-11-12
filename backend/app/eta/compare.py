"""So sánh ETA luật (P50/P90 theo khung giờ) với ETA ML cho một chuyến giả định — logic của `POST /v1/eta/predict`,
tách ra để endpoint đó và ETA Sandbox dùng CHUNG một đường tính (không có hai bản)."""
from datetime import datetime, timedelta

from . import baseline, ml


def rule_vs_ml(params: dict, depart_at: datetime, km: float = ml.BASE_KM, ctx: dict | None = None) -> dict:
    """ETA luật (có P50/P90 theo khung giờ) và ETA ML (nếu đã promote); `used` cho biết bên nào đang được dùng."""
    ml.ensure_trained(params["transit_minutes"])
    base = params["transit_minutes"] * (km / ml.BASE_KM)
    p50 = depart_at + timedelta(minutes=base)
    rule = baseline.interval(p50, base, depart_at, params)
    pred = ml.predict(depart_at, km, ctx)
    return {"rule": {**rule, "minutes_p50": round(base), "method": "rule-based", "confidence": "low (rule-based)"}, "ml": pred,
            "used": "ml" if pred else "rule", "status": ml.model_info()["status"], "is_simulated": True}
