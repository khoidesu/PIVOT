"""Bản nháp nhập liệu (DRAFT 6.1). Nguyên tắc cứng:
  - Chỉ tạo BẢN NHÁP. Người dùng phải duyệt rồi mới tạo yêu cầu có hiệu lực (qua POST /v1/shipments, vẫn validate đầy đủ).
  - Trường thiếu/không chắc → null + needs_review; KHÔNG suy đoán. Giá trị không có trích đoạn nguồn thật trong văn bản bị bỏ.
  - Văn bản là dữ liệu không tin cậy: chỉ dẫn trong đó không bao giờ được thực thi; chỉ gắn cờ cảnh báo.
  - Kiểm tra bằng LUẬT (kiểu, đơn vị, khoảng, thứ tự giờ); không dùng 'confidence' do mô hình tự khai.
  - Ngày tương đối ("mai") giải theo thời điểm nguồn + múi giờ VN và LUÔN yêu cầu xác nhận.
"""
import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .extractor import FIELDS, VN, Extractor, strip_accents

MAX_CHARS = 8000
REQUIRED = ("cargo_type", "weight_kg", "volume_m3", "origin", "dest", "ready_at", "pickup_deadline", "cutoff_at")
MAX_WEIGHT_KG, MAX_VOLUME_M3 = 60_000, 150
INJECTION_RE = re.compile(
    r"ignore (?:all |any |the )?(?:previous|prior|above)|disregard (?:the )?(?:previous|above)|system prompt|you are now|"
    r"bỏ qua (?:mọi|các|tất cả)? ?(?:hướng dẫn|chỉ dẫn|lệnh)|tự động (?:xác nhận|accept|duyệt)|auto-?accept|"
    r"(?:xác nhận|accept|confirm) (?:booking|đề xuất|proposal)|xoá|delete (?:all|database)", re.I)


def _field(value: Any = None, quote: str | None = None, start: int | None = None, end: int | None = None,
           status: str = "needs_review", notes: list[str] | None = None, display: str | None = None) -> dict:
    return {"value": value, "display": display if display is not None else (None if value is None else str(value)),
            "source": None if quote is None else {"quote": quote, "start": start, "end": end},
            "status": status, "notes": notes or []}


def _locate(text: str, quote: str | None) -> tuple[int, int] | None:
    if not quote or not isinstance(quote, str):
        return None
    i = text.find(quote)
    if i < 0:
        i = text.lower().find(quote.lower())
    return (i, i + len(quote)) if i >= 0 else None


def _match_location(name: Any, locations: list[dict], kind_icd: bool) -> dict | None:
    if not isinstance(name, str):
        return None
    n = strip_accents(name).lower()
    pool = [l for l in locations if (l["kind"] == "icd") == kind_icd]
    exact = [l for l in pool if strip_accents(re.sub(r"\s*\(.*?\)", "", l["name"])).lower() == n or n in strip_accents(l["name"]).lower()]
    return exact[0] if len(exact) == 1 else None


def _parse_dt(v: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return d if d.tzinfo else None  # thiếu múi giờ → không chấp nhận


def build_draft(text: str, now: datetime, locations: list[dict], extractor: Extractor) -> dict:
    text = text[:MAX_CHARS]
    raw = extractor.extract(text, now, locations)
    fields: dict[str, dict] = {}

    for name in FIELDS:
        r = raw.get(name) or {}
        value, quote = r.get("value"), r.get("quote")
        notes: list[str] = []
        span = _locate(text, quote)
        if value is None:
            fields[name] = _field(notes=["AMBIGUOUS" if r.get("ambiguous") else "MISSING"] + ([f"candidates: {r['candidates']}"] if r.get("candidates") else []))
            continue
        if span is None:  # không bịa: giá trị không có trích đoạn nguồn thật → bỏ
            fields[name] = _field(notes=["QUOTE_NOT_FOUND_IN_SOURCE"])
            continue
        s, e = span
        quote = text[s:e]

        ok = True
        if name == "cargo_type":
            ok = value in ("dry", "cold")
            display = {"dry": "Hàng khô", "cold": "Hàng lạnh"}.get(value, str(value))
        elif name in ("weight_kg", "volume_m3"):
            hi = MAX_WEIGHT_KG if name == "weight_kg" else MAX_VOLUME_M3
            ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= hi
            display = f"{value:g} {'kg' if name == 'weight_kg' else 'm³'}" if ok else str(value)
        elif name in ("origin", "dest"):
            loc = _match_location(value, locations, kind_icd=(name == "dest"))
            ok = loc is not None
            value, display = (loc["id"], loc["name"]) if loc else (None, str(r.get("value")))
        elif name in ("ready_at", "pickup_deadline", "cutoff_at"):
            d = _parse_dt(value)
            ok = d is not None
            value, display = (d.astimezone(timezone.utc).isoformat(), d.astimezone(VN).strftime("%d/%m/%Y %H:%M")) if d else (None, str(value))
            if ok and r.get("relative"):
                notes.append("RELATIVE_DATE_ASSUMED")  # "mai/hôm nay/chỉ có giờ": phải được người dùng xác nhận
        elif name == "price_vnd":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 10**11
            display = f"{int(value):,} ₫" if ok else str(value)
        else:  # customer_name
            ok = isinstance(value, str) and 0 < len(value.strip()) <= 200
            value = value.strip() if ok else None
            display = value
        if not ok:
            notes.append("INVALID_VALUE")
            fields[name] = _field(None, quote, s, e, "needs_review", notes, display=display)
            continue
        status = "needs_review" if "RELATIVE_DATE_ASSUMED" in notes else "ok"
        fields[name] = _field(value, quote, s, e, status, notes, display=display)

    # thứ tự thời gian ready < pickup_deadline < cutoff
    t = {k: _parse_dt(fields[k]["value"]) for k in ("ready_at", "pickup_deadline", "cutoff_at")}
    if all(t.values()) and not (t["ready_at"] < t["pickup_deadline"] < t["cutoff_at"]):
        for k in t:
            fields[k]["status"] = "needs_review"
            fields[k]["notes"].append("TIME_ORDER_INVALID")
    elif t["ready_at"] and t["pickup_deadline"] and not t["ready_at"] < t["pickup_deadline"]:
        for k in ("ready_at", "pickup_deadline"):
            fields[k]["status"], _ = "needs_review", fields[k]["notes"].append("TIME_ORDER_INVALID")

    for k in REQUIRED:
        if fields[k]["value"] is None:
            fields[k]["status"] = "needs_review"
    needs_review = [k for k in FIELDS if fields[k]["status"] == "needs_review" and (k in REQUIRED or fields[k]["value"] is not None or fields[k]["notes"] not in ([], ["MISSING"]))]
    return {
        "draft_id": str(uuid.uuid4()),
        "extractor": {"name": extractor.name, "kind": extractor.kind},
        "source": {"length": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()},
        "reference_time": now.astimezone(VN).isoformat(),
        "fields": fields,
        "needs_review": needs_review,
        "complete": all(fields[k]["value"] is not None for k in REQUIRED),
        "suspicious_instructions": bool(INJECTION_RE.search(text)),
        "is_draft_only": True,
    }
