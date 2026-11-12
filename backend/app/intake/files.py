"""Tệp (PDF hoặc ảnh) → BẢN NHÁP. Dùng chung cho API (/v1/intake/drafts/file) và công cụ chạy bộ tệp demo
(`python -m app.intake_file_eval_cli`), để hai nơi đi đúng một đường xử lý.

  - PDF có lớp chữ  → lấy chữ trong máy chủ → build_draft với bộ trích xuất của TIN NHẮN (luật + Gemini văn bản đã che).
  - PDF scan        → vẽ trang thành JPEG → đọc như ảnh.
  - Ảnh JPEG/PNG/WebP → gỡ EXIF → đọc ảnh (Gemini) → bộ luật bù trường còn trống trên bản phiên âm → mọi trường "cần xem lại".
Loại tệp quyết định theo NỘI DUNG. Không lưu tệp; trả kèm `audit` chỉ gồm số đo (không chữ, không ảnh).
"""
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .extractor import FIELDS, RuleExtractor, StaticExtractor, sniff_image, strip_jpeg_metadata
from .pdf import PDF_MIME, PdfError, is_pdf, open_pdf, render_pages
from .service import MAX_CHARS, build_draft, mark_image_draft

# đọc ảnh: [(bytes, mime), …] → (các trường, bản phiên âm) | None (mô hình lỗi). Có thể ném FileIntakeError (vd hết lượt).
ImageReader = Callable[[list[tuple[bytes, str]]], tuple[dict[str, dict[str, Any]], str] | None]


class FileIntakeError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _from_images(images: list[tuple[bytes, str]], now: datetime, locs: list[dict], read_images: ImageReader, reader_name: str) -> dict:
    got = read_images(images)
    if got is None:
        raise FileIntakeError(503, "IMAGE_UNREADABLE", "The image could not be read. Try a sharper photo or try again later")
    fields, transcript = got
    # Gemini có lúc bỏ sót trường (kết quả đọc ảnh dao động giữa các lần): trường còn trống thì thử bộ luật trên BẢN PHIÊN ÂM
    for k, v in RuleExtractor().extract(transcript, now, locs).items():
        if k in FIELDS and (fields.get(k) or {}).get("value") is None and v.get("value") is not None:
            fields[k] = v
    return mark_image_draft(build_draft(transcript, now, locs, StaticExtractor(reader_name, fields)), images[0][1], transcript)


def draft_from_file(data: bytes, now: datetime, locs: list[dict], *, text_extractor, read_images: ImageReader | None,
                    reader_name: str, cfg) -> tuple[dict, dict]:
    """→ (bản nháp, audit). Lỗi tệp/đọc → FileIntakeError (mã rõ ràng, không bao giờ trả bản nháp trống)."""
    if is_pdf(data):
        if not cfg.intake_pdf_enabled:
            raise FileIntakeError(501, "PDF_INTAKE_DISABLED", "PDF intake is not enabled on this server")
        if len(data) > cfg.intake_pdf_max_bytes:
            raise FileIntakeError(413, "PDF_TOO_LARGE", f"PDF must be at most {cfg.intake_pdf_max_bytes // 1_000_000} MB")
        try:
            doc = open_pdf(data, cfg.intake_pdf_max_pages)
        except PdfError as e:
            raise FileIntakeError(e.status, e.code, e.message) from None
        if doc.has_text(cfg.intake_pdf_min_letters):
            draft = build_draft(doc.text, now, locs, text_extractor)
            draft["source"] = {**draft["source"], "kind": "pdf_text", "mime": PDF_MIME, "pages": doc.pages}
            draft["transcript"] = doc.text[:MAX_CHARS]
        else:
            if read_images is None:  # PDF scan cần đọc ảnh; máy chủ chưa bật → nói rõ
                raise FileIntakeError(422, "PDF_SCAN_NEEDS_IMAGE_READING", "This PDF has no text layer (scanned) and image reading is not enabled")
            draft = _from_images(render_pages(doc), now, locs, read_images, reader_name)
            draft["source"] = {**draft["source"], "kind": "pdf_scan", "mime": PDF_MIME, "pages": doc.pages}
        return draft, {"pdf": {"bytes": len(data), "pages": doc.pages, "kind": draft["source"]["kind"]}}

    mime = sniff_image(data)  # loại ảnh theo NỘI DUNG, không tin đuôi tệp/khai báo
    if mime is None:
        raise FileIntakeError(415, "UNSUPPORTED_FILE", "Only PDF, JPEG, PNG or WebP files are accepted")
    if len(data) > cfg.intake_image_max_bytes:
        raise FileIntakeError(413, "IMAGE_TOO_LARGE", f"Image must be at most {cfg.intake_image_max_bytes // 1_000_000} MB")
    if read_images is None:
        raise FileIntakeError(501, "IMAGE_INTAKE_DISABLED", "Image intake is not enabled on this server")
    data = strip_jpeg_metadata(data)  # bỏ EXIF (có thể chứa toạ độ GPS) trước khi gửi ra ngoài
    return _from_images([(data, mime)], now, locs, read_images, reader_name), {"image": {"mime": mime, "bytes": len(data)}}
