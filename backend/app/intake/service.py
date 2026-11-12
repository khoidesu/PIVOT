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
from datetime import datetime, timezone, timedelta
from typing import Any

from .vn_names import person_likeness
from .extractor import FIELDS, VN, Extractor, strip_accents

MAX_CHARS = 8000
REQUIRED = ("cargo_type", "weight_kg", "volume_m3", "origin", "dest", "ready_at", "pickup_deadline", "cutoff_at")
MAX_WEIGHT_KG, MAX_VOLUME_M3 = 60_000, 150
INJECTION_RE = re.compile(
    r"ignore (?:all |any |the )?(?:previous|prior|above)|disregard (?:the )?(?:previous|above)|system prompt|you are now|"
    r"bỏ qua (?:mọi|các|tất cả)? ?(?:hướng dẫn|chỉ dẫn|lệnh|kiểm tra|quy tắc|điều kiện|ràng buộc)|tự động (?:xác nhận|accept|duyệt)|auto-?accept|"
    r"(?:xác nhận|accept|confirm|duyệt) (?:booking|đề xuất|proposal|đơn|đơn hàng)(?: này)?|duyệt luôn|xoá|delete (?:all|database)", re.I)
MULTI_RE = re.compile(r"\b(?:lô|đơn)\s*(?:1|một)\b.*?\b(?:lô|đơn)\s*(?:2|hai)\b|\b(?:[2-9]|hai|ba|bốn|năm)\s+(?:lô|đơn|chuyến)\b", re.I | re.S)
REQUEST_RE = re.compile(r"chở|vận chuyển|lô hàng|container|\bxe\b|\d\s*(?:tấn|kg|khối|m3|m³)|\b(?:ship|transport|cargo)\b", re.I)
_PL = r"(?:(?:kho|KCN|kcn|xưởng|cảng|ICD|icd|depot|chợ đầu mối|chợ|showroom|nhà máy|bãi|cụm công nghiệp)\s+)?[A-ZÀ-Ỹ][\wÀ-ỹ]*(?:\s+[A-ZÀ-Ỹ][\wÀ-ỹ]*){0,3}(?:\s+(?:\d{1,2}\b|cảng\b))?"
PLACE_PAIR_RE = re.compile(rf"\btừ\s+(?P<o>{_PL})\s*(?:đến|tới|ra|về|đi|->|→|-)\s*(?P<d>{_PL})")
PLACE_ONE_RE = {"origin": re.compile(rf"\b(?:từ|lấy (?:hàng )?tại|tại)\s+(?P<p>{_PL})"), "dest": re.compile(rf"\b(?:đến|tới|ra|giao (?:tại|cho|ở)?)\s+(?P<p>{_PL})")}
HOUR_RE = re.compile(r"\d\s*(?:h|giờ|g\b|:|am\b|pm\b|a\.m|p\.m|o.?clock|hrs?\b)", re.I)


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
        if name in ("origin", "dest") and ((e < len(text) and text[e].isalnum()) or (s > 0 and text[s - 1].isalnum())):
            fields[name] = _field(notes=["QUOTE_NOT_FOUND_IN_SOURCE"])  # trích đoạn chỉ là một phần của từ khác ("cảng C" trong "cảng Cát Lái")
            continue
        if name in ("ready_at", "pickup_deadline", "cutoff_at") and not HOUR_RE.search(quote):
            fields[name] = _field(notes=["TIME_VAGUE"])  # chỉ có buổi/"hôm nay"/"cùng ngày", không có giờ cụ thể → không đoán giờ
            continue

        ok = True
        if name == "cargo_type":
            ok = value in ("dry", "cold")
            if ok and not re.search(r"khô|\bdry\b|lạnh|đông|cold|reefer|mát", quote, re.I):
                notes.append("CARGO_INFERRED")  # mô hình suy ra từ loại mặt hàng ("dệt may" → khô): không phải điều tin nhắn nói
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
            if ok and d < now - timedelta(minutes=5):
                notes.append("TIME_IN_PAST")  # giờ đã qua so với thời điểm tham chiếu (vd "thứ 5 này lúc 6h" khi đã quá 6h)
        elif name == "price_vnd":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 10**11
            display = f"{int(value):,} ₫" if ok else str(value)
        else:  # customer_name
            ok = isinstance(value, str) and 0 < len(value.strip()) <= 200
            value = value.strip() if ok else None
            display = value
            if ok and person_likeness(value) == "low":
                notes.append("NAME_UNCERTAIN")  # không giống tên người/công ty (số điện thoại, địa điểm, loại hàng…) → người dùng phải xem lại
        if not ok:
            notes.append("INVALID_VALUE")
            fields[name] = _field(None, quote, s, e, "needs_review", notes, display=display)
            continue
        status = "needs_review" if any(n in notes for n in ("RELATIVE_DATE_ASSUMED", "CARGO_INFERRED", "TIME_IN_PAST", "NAME_UNCERTAIN")) else "ok"
        fields[name] = _field(value, quote, s, e, status, notes, display=display)

    # một đoạn chữ chỉ được điền MỘT trường giờ (vd "lấy hàng lúc 8h" không đồng thời là ready_at và pickup_deadline): giữ trường đầu theo thứ tự ready > pickup > cutoff
    seen: set[tuple[int, int]] = set()
    for k in ("ready_at", "pickup_deadline", "cutoff_at"):
        sp = (fields[k]["source"]["start"], fields[k]["source"]["end"]) if fields[k]["value"] is not None and fields[k].get("source") else None
        if sp and sp in seen:
            fields[k] = _field(notes=["DUPLICATE_TIME_SOURCE"])
        elif sp:
            seen.add(sp)
    # "giao trước 15h cùng ngày" → cùng ngày với giờ hàng sẵn sàng (không phải hôm nay)
    rd = _parse_dt(fields["ready_at"]["value"]) if fields["ready_at"]["value"] else None
    for k in ("pickup_deadline", "cutoff_at"):
        f = fields[k]
        q = (f.get("source") or {}).get("quote") or ""
        tail = text[(f.get("source") or {}).get("end") or 0:][:16]  # mô hình hay cắt trích đoạn ngay trước "cùng ngày"
        if rd and f["value"] is not None and re.search(r"cùng ngày|trong ngày", q + " " + tail, re.I) and not re.search(r"\d{1,2}/\d{1,2}|\bmai\b|\bnay\b|ngày kia", q, re.I):
            d = _parse_dt(f["value"]).astimezone(VN)
            rv = rd.astimezone(VN)
            d = d.replace(year=rv.year, month=rv.month, day=rv.day)
            f["value"], f["display"] = d.astimezone(timezone.utc).isoformat(), d.strftime("%d/%m/%Y %H:%M")
            f["status"] = "needs_review"
            f["notes"] = [n for n in f["notes"] if n != "TIME_IN_PAST"] + (["RELATIVE_DATE_ASSUMED"] if "RELATIVE_DATE_ASSUMED" not in f["notes"] else [])
    # thứ trong tuần ghi trong tin phải khớp ngày đã suy ra (mô hình hay tính sai thứ; tin cũng có thể ghi sai: "T4 (13/11)" nhưng 13/11 là thứ Sáu)
    _wd = {"hai": 0, "ba": 1, "tư": 2, "năm": 3, "sáu": 4, "bảy": 5, "2": 0, "3": 1, "4": 2, "5": 3, "6": 4, "7": 5}
    for k in ("ready_at", "pickup_deadline", "cutoff_at"):
        f = fields[k]
        if f["value"] is None or not f.get("source"):
            continue
        ctx = text[max(0, f["source"]["start"] - 12): f["source"]["end"] + 12]
        w = re.search(r"thứ\s*(hai|ba|tư|năm|sáu|bảy|[2-7])\b|\bt([2-7])\b", ctx, re.I)
        if w:
            want = _wd[(w.group(1) or w.group(2)).lower()]
            if _parse_dt(f["value"]).astimezone(VN).weekday() != want and "WEEKDAY_MISMATCH" not in f["notes"]:
                f["status"] = "needs_review"
                f["notes"].append("WEEKDAY_MISMATCH")
    # thứ tự thời gian ready < pickup_deadline < cutoff
    t = {k: _parse_dt(fields[k]["value"]) for k in ("ready_at", "pickup_deadline", "cutoff_at")}
    if all(t.values()) and not (t["ready_at"] < t["pickup_deadline"] < t["cutoff_at"]):
        for k in t:
            fields[k]["status"] = "needs_review"
            fields[k]["notes"].append("TIME_ORDER_INVALID")
    elif t["ready_at"] and t["pickup_deadline"] and not t["ready_at"] < t["pickup_deadline"]:
        for k in ("ready_at", "pickup_deadline"):
            fields[k]["status"], _ = "needs_review", fields[k]["notes"].append("TIME_ORDER_INVALID")
    elif t["ready_at"] and t["cutoff_at"] and not t["pickup_deadline"] and not t["ready_at"] < t["cutoff_at"]:
        for k in ("ready_at", "cutoff_at"):
            fields[k]["status"], _ = "needs_review", fields[k]["notes"].append("TIME_ORDER_INVALID")

    for k in ("origin", "dest"):  # tin CÓ nêu địa điểm nhưng không nằm trong danh sách hệ thống: nói rõ thay vì "không thấy trong văn bản"
        f = fields[k]
        if f["value"] is not None or f["notes"] not in (["MISSING"], ["QUOTE_NOT_FOUND_IN_SOURCE"], []):
            continue
        pm = PLACE_PAIR_RE.search(text)
        mm = (pm if pm and pm.group("o" if k == "origin" else "d") else None)
        span = mm.span("o" if k == "origin" else "d") if mm else None
        if not span:
            one = PLACE_ONE_RE[k].search(text)
            span = one.span("p") if one else None
        if span and len(text[span[0]:span[1]].strip()) >= 3:
            q = text[span[0]:span[1]].strip()
            fields[k] = _field(None, q, span[0], span[0] + len(q), "needs_review", ["PLACE_NOT_IN_SYSTEM"])
    for k in REQUIRED:
        if fields[k]["value"] is None:
            fields[k]["status"] = "needs_review"
    multiple = bool(MULTI_RE.search(text))
    if multiple:  # tin có nhiều lô: một bản nháp = một lô → mọi giá trị phải xem lại, người dùng tạo từng lô riêng
        for f in fields.values():
            if f["value"] is not None:
                f["status"] = "needs_review"
                f["notes"].append("MULTIPLE_SHIPMENTS")
    looks = any(fields[k]["value"] is not None for k in FIELDS) or bool(REQUEST_RE.search(text))
    needs_review = [k for k in FIELDS if fields[k]["status"] == "needs_review" and (k in REQUIRED or fields[k]["value"] is not None or fields[k]["notes"] not in ([], ["MISSING"]))]
    return {
        "draft_id": str(uuid.uuid4()),
        "extractor": {"name": extractor.name, "kind": extractor.kind, **({"note": extractor.note} if getattr(extractor, "note", None) else {})},
        "source": {"length": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()},
        "reference_time": now.astimezone(VN).isoformat(),
        "fields": fields,
        "needs_review": needs_review,
        "complete": all(fields[k]["value"] is not None for k in REQUIRED),
        "suspicious_instructions": bool(INJECTION_RE.search(text)),
        "multiple_shipments": multiple,
        "looks_like_request": looks,  # false: tin không giống một yêu cầu vận chuyển (hỏi giá, cảm ơn…) — cảnh báo, không chặn
        "is_draft_only": True,
    }


def mark_image_draft(draft: dict, mime: str, transcript: str) -> dict:
    """Bản nháp từ ẢNH: trích đoạn kiểm theo bản phiên âm (không phải ảnh), nên mọi trường có giá trị đều phải được người dùng xem lại
    (cho tới khi đo được độ chính xác trên ảnh thật — DRAFT 6.1)."""
    for name, f in draft["fields"].items():
        if f["value"] is not None:
            f["status"] = "needs_review"
            if "FROM_IMAGE" not in f["notes"]:
                f["notes"].append("FROM_IMAGE")
    draft["needs_review"] = [k for k in FIELDS if draft["fields"][k]["value"] is not None or k in REQUIRED]
    draft["source"] = {**draft["source"], "kind": "image", "mime": mime}
    draft["transcript"] = transcript
    return draft
