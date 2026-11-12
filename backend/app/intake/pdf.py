"""Đọc tệp PDF cho nhập liệu (DRAFT 6.1: "tải một PDF văn bản/ảnh phiếu… trích văn bản/OCR nếu cần").

Hai nhánh, quyết định theo NỘI DUNG tệp:
  - PDF có lớp chữ (in từ Word/Excel/hộp thư): lấy chữ ngay trong máy chủ → CÙNG đường xử lý với tin nhắn dán vào
    (luật trước, Gemini bổ sung phần thiếu và chỉ nhận văn bản đã che giá/tên khách). Tệp không rời máy chủ.
  - PDF scan (chỉ có ảnh): vẽ từng trang thành ảnh JPEG (chỉ còn điểm ảnh — bỏ metadata, JavaScript, tệp đính kèm của PDF)
    rồi đưa Gemini đọc như ảnh. Mọi trường "cần xem lại".

Tệp là dữ liệu KHÔNG TIN CẬY: chỉ đọc chữ/vẽ trang, không chạy JavaScript, không mở tệp đính kèm hay liên kết.
PDFium không an toàn khi chạy song song nhiều luồng → mọi lệnh gọi đi qua một khoá.
"""
import io
import re
import threading
import unicodedata
from dataclasses import dataclass

PDF_MIME = "application/pdf"
RENDER_DPI = 150  # đủ nét để đọc chữ trên phiếu A4
MAX_SIDE = 1600   # cạnh dài tối đa của ảnh trang (khớp giới hạn ảnh ở trình duyệt); chặn cả trang PDF kích thước bất thường
_LOCK = threading.Lock()
_PASSWORD_ERR = 4  # FPDF_ERR_PASSWORD


class PdfError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class PdfDoc:
    data: bytes
    pages: int
    text: str        # lớp chữ của mọi trang (NFC), các trang cách nhau một dòng trống
    letters: int     # số chữ cái trong lớp chữ — để quyết định PDF có chữ hay PDF scan

    def has_text(self, min_letters: int) -> bool:
        return self.letters >= min_letters


def is_pdf(data: bytes) -> bool:
    """Theo nội dung: chữ ký %PDF- nằm trong 1 KB đầu (chuẩn PDF cho phép rác phía trước)."""
    return b"%PDF-" in data[:1024]


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+", " ", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def open_pdf(data: bytes, max_pages: int) -> PdfDoc:
    import pypdfium2 as pdfium

    with _LOCK:
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as e:
            if getattr(e, "err_code", None) == _PASSWORD_ERR:
                raise PdfError(422, "PDF_ENCRYPTED", "Password-protected PDFs are not accepted") from None
            raise PdfError(422, "BAD_PDF", "The PDF could not be opened") from None
        try:
            n = len(pdf)
            if n == 0:
                raise PdfError(422, "BAD_PDF", "The PDF has no pages")
            if n > max_pages:
                raise PdfError(413, "PDF_TOO_MANY_PAGES", f"PDF must have at most {max_pages} pages")
            texts = []
            for i in range(n):
                page = pdf[i]
                tp = page.get_textpage()
                texts.append(_clean(tp.get_text_range()))
                tp.close()
                page.close()
        finally:
            pdf.close()
    text = "\n\n".join(t for t in texts if t)
    return PdfDoc(data=data, pages=n, text=text, letters=sum(ch.isalpha() for ch in text))


def render_pages(doc: PdfDoc, quality: int = 85) -> list[tuple[bytes, str]]:
    """Từng trang → JPEG (chỉ điểm ảnh, không mang metadata của PDF). Trả [(bytes, "image/jpeg"), …] theo thứ tự trang."""
    import pypdfium2 as pdfium

    out: list[tuple[bytes, str]] = []
    with _LOCK:
        pdf = pdfium.PdfDocument(doc.data)
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                w, h = page.get_size()
                scale = min(RENDER_DPI / 72, MAX_SIDE / max(w, h, 1))
                bmp = page.render(scale=scale)
                img = bmp.to_pil().convert("RGB")
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=quality)
                out.append((buf.getvalue(), "image/jpeg"))
                bmp.close()
                page.close()
        finally:
            pdf.close()
    return out
