"""Nhận dạng TÊN NGƯỜI Việt trong tin nhắn bằng gợi ý ngôn ngữ (không phải mô hình): đại từ xưng hô + chữ hoa, họ phổ biến + tên đệm + tên, tên công ty.

Dùng ở hai nơi: (1) bộ luật `RuleExtractor._customer` để tìm tên khi người dùng không ghi nhãn "khách:"; (2) `build_draft` để chấm độ chắc chắn của
`customer_name` từ BẤT KỲ bộ trích xuất nào (kể cả Gemini) — giá trị không giống tên người/công ty → "cần xem lại" (`NAME_UNCERTAIN`), không bị loại.
Danh sách chỉ là gợi ý (tên phổ biến, không đầy đủ); tên lạ nhưng viết hoa sau "anh/chị/ông/bà…" vẫn được nhận."""
import re
import unicodedata

SURNAMES = ("Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý", "Đinh", "Đoàn",
            "Trịnh", "Mai", "Lâm", "Hà", "Cao", "Tạ", "Tô", "Lương", "Châu", "Thái", "Văn", "Quách", "Tăng", "La", "Diệp", "Trương", "Lưu", "Tống")
MIDDLES = ("Văn", "Thị", "Hữu", "Đức", "Ngọc", "Minh", "Quốc", "Thanh", "Công", "Xuân", "Hồng", "Kim", "Gia", "Bảo", "Anh", "Thế", "Duy", "Mạnh", "Tuấn", "Việt", "Đình", "Quang")
GIVEN = ("An", "Anh", "Bình", "Châu", "Chi", "Cường", "Dũng", "Dương", "Đạt", "Đức", "Giang", "Hà", "Hải", "Hằng", "Hạnh", "Hiếu", "Hoa", "Hòa", "Hoàng", "Hồng",
         "Huy", "Hùng", "Hương", "Hưng", "Khánh", "Khoa", "Khôi", "Kiên", "Lan", "Lâm", "Linh", "Loan", "Long", "Lộc", "Mai", "Minh", "My", "Nam", "Nga", "Ngân", "Nghĩa",
         "Ngọc", "Nguyên", "Nhân", "Như", "Oanh", "Phát", "Phong", "Phú", "Phúc", "Phước", "Phương", "Quân", "Quang", "Quý", "Quyên", "Sơn", "Tài", "Tâm", "Tân", "Thái",
         "Thanh", "Thảo", "Thắng", "Thịnh", "Thu", "Thúy", "Thủy", "Tiến", "Toàn", "Trang", "Trâm", "Trí", "Trung", "Trường", "Tuấn", "Tú", "Tùng", "Tuyết", "Uyên",
         "Vân", "Vinh", "Vũ", "Vy", "Yến", "Hân", "Hậu", "Hiền", "Hiệp", "Huệ", "Huyền", "Kim", "Lệ", "Liên", "Nhung", "Quỳnh", "Sang", "Thọ", "Thuận", "Tiên", "Tín",
         "Trinh", "Tuân", "Việt", "Xuân", "Đạo", "Đông", "Đại", "Điệp", "Bảo", "Bích", "Cẩm", "Dung", "Duy", "Duyên", "Hiển", "Khang", "Khuê", "Luân", "Mạnh", "Nhi",
         "Nhật", "Ninh", "Phượng", "Thiện", "Thông", "Tình", "Thành", "Đạt", "Tuyên", "Hạ", "Hoài", "Lợi", "Nhàn", "Sương", "Tâm", "Hiếu", "Cương", "Lực", "Phi")
HONORIFICS = ("anh", "chị", "ông", "bà", "cô", "chú", "bác", "em", "a", "c")
COMPANY_RE = re.compile(r"\b(?:cty|c\.ty|công ty|tnhh|cổ phần|jsc|co\.?,? ?ltd|ltd|xí nghiệp|doanh nghiệp|dn)\b", re.I)
# tên riêng của người dễ trùng với từ thường khi viết thường (mai = ngày mai, nam = hướng nam…): chỉ nhận khi VIẾT HOA
AMBIGUOUS_LOWER = {"mai", "nam", "thu", "sang", "phi", "hạ", "tài", "lực", "chi", "an", "anh", "hoa", "long", "tân", "kim", "văn", "minh", "hà"}
NOT_NAME_WORDS = {"ơi", "oi", "nhé", "nha", "à", "ạ", "có", "cần", "ở", "cho", "đi", "ra", "đến", "giúp", "xem", "biết", "nói", "ok", "và", "với", "là", "đã", "không",
                  "thì", "nào", "hỏi", "gửi", "báo", "ới", "này", "đó", "kia", "bên", "em", "mình", "tôi", "tui", "sẽ", "đang", "muốn", "lấy", "giao", "chở", "xe", "hàng"}
PLACE_PREFIX = re.compile(r"(?:\b(?:từ|đến|tới|ra|tại|ở|về|qua|đi|kho|xưởng|kcn|icd|cảng|quận|huyện|phường|xã|đường|phố|tp|thành phố|tỉnh)\.?\s*)$", re.I)
PLACE_PHRASES = ("hồ chí minh", "phan thiết", "phan rang", "trần đề", "lê chân", "đặng văn bi", "võ văn kiệt", "nguyễn văn linh", "trần phú", "phạm văn đồng")


def _strip(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


_SUR, _MID, _GIV = ({_strip(x) for x in g} for g in (SURNAMES, MIDDLES, GIVEN))
_CAP = r"[A-ZÀ-ỸĐ][A-Za-zÀ-ỹđĐ]*"  # từ viết hoa chữ đầu (có dấu)
_WORD = r"[A-Za-zÀ-ỹđĐ]+"


def _is_cap(w: str) -> bool:
    return bool(w) and w[0].isupper()


def _known_given(w: str) -> bool:
    return _strip(w) in _GIV or _strip(w) in _MID or _strip(w) in _SUR


def find_person(text: str, exclude: list[tuple[int, int]] | None = None) -> tuple[str, str] | None:
    """(tên, trích đoạn nguyên văn) hoặc None. Thứ tự ưu tiên: Cty/Công ty → họ + tên viết hoa → xưng hô + tên."""
    ex = exclude or []

    def bad(s: int, e: int) -> bool:
        return any(s < b and a < e for a, b in ex) or bool(PLACE_PREFIX.search(text[max(0, s - 14):s])) or text[s:e].lower() in PLACE_PHRASES

    m = re.search(rf"\b((?i:cty|c\.ty|công ty)\s+(?:(?i:tnhh|cổ phần|cp)\s+)?{_WORD}(?:\s+{_CAP}){{0,3}})", text)
    if m and not bad(m.start(), m.end()):
        return m.group(1).strip(), m.group(1).strip()
    for m in re.finditer(rf"(?<!\w)({'|'.join(SURNAMES)})((?:\s+{_CAP}){{1,3}})(?!\w)", text):  # "Nguyễn Văn An": họ + 1–3 từ viết hoa
        if bad(m.start(), m.end()):
            continue
        rest = m.group(2).split()
        if rest and not any(w.lower() in NOT_NAME_WORDS for w in rest):
            return m.group(0).strip(), m.group(0).strip()
    for m in re.finditer(rf"(?<!\w)({'|'.join(HONORIFICS)})\s+({_WORD})((?:\s+{_CAP}){{0,2}})", text, re.I):
        hon, w1, more = m.group(1), m.group(2), m.group(3)
        if hon.lower() in ("a", "c", "em") and not (_is_cap(w1) or _known_given(w1)):
            continue
        if w1.lower() in NOT_NAME_WORDS or bad(m.start(), m.end()):
            continue
        if _is_cap(w1) or (_strip(w1) in (_GIV | _MID | _SUR) and w1.lower() not in AMBIGUOUS_LOWER):
            name = (w1 + more).strip()
            if any(t.lower() in NOT_NAME_WORDS for t in name.split()):
                name = name.split()[0]
            q = text[m.start():m.start(2) + len(name)]
            return q.strip(), q.strip()
    return None


def person_likeness(value: str) -> str:
    """'ok' nếu giống tên người/công ty, 'low' nếu không (số điện thoại, địa điểm, từ thường…)."""
    v = (value or "").strip()
    if not v or len(v) > 80 or re.search(r"\d", v):
        return "low"
    if COMPANY_RE.search(v):
        return "ok"
    toks = v.split()
    if toks and toks[0].lower() in HONORIFICS:
        toks = toks[1:]
    if not toks or len(toks) > 6 or any(t.lower() in NOT_NAME_WORDS or t.lower() in ("kho", "cảng", "kcn", "icd", "tấn", "kg", "khối") for t in toks):
        return "low"
    if any(_known_given(t) for t in toks):
        return "ok"
    return "ok" if all(_is_cap(t) for t in toks) else "low"  # tên lạ nhưng viết hoa (danh từ riêng) vẫn nhận
