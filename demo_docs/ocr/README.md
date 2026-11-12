# Bộ tệp DEMO — nhập liệu từ PDF / ảnh (DRAFT mục 6.1)

Thư mục này chứa **tài liệu mô phỏng** để chạy demo và kiểm thử chức năng "tải PDF/ảnh phiếu → bản nháp yêu cầu vận chuyển".
Mọi tên công ty, tên người, số điện thoại, email đều **hư cấu**; mỗi tệp có dòng *"TÀI LIỆU MÔ PHỎNG - LOGECTION DEMO"*.
Đây **không** phải dữ liệu thật và **không** chứng minh độ chính xác trên chứng từ thật.

```
demo_docs/ocr/
├── files/              17 tệp để tải lên (PDF, JPG, PNG)
├── expected/           đáp án cho từng tệp (cùng tên, đuôi .json)
├── make_demo_files.py  script sinh lại toàn bộ files/ + expected/ từ một nguồn dữ liệu
└── README.md
```

## Hệ thống xử lý một tệp như thế nào

| Loại tệp | Đường xử lý | Cần khoá Gemini? | Tốn lượt ảnh? |
|---|---|---|---|
| **PDF có lớp chữ** (in từ Word/Excel/email) | Chữ lấy **ngay trong máy chủ** (pypdfium2) → cùng đường với tin nhắn dán: bộ luật trước, chế độ `hybrid` thì Gemini bổ sung trường thiếu (giá + tên khách được che `[ẩn]` trước khi gửi). Tệp không rời máy chủ. | Không (có thì tốt hơn) | Không |
| **PDF scan** (chỉ có ảnh) | Vẽ từng trang thành JPEG (bỏ hết metadata/JavaScript/đính kèm của PDF) → Gemini đọc như ảnh | Có | 1 lượt / tệp |
| **Ảnh** JPG / PNG / WebP | Gỡ EXIF (toạ độ GPS) → Gemini đọc → bộ luật bù trường còn trống trên bản phiên âm | Có | 1 lượt / tệp |
| Tệp khác / PDF > 3 trang / > 5 MB / có mật khẩu | **Từ chối** trước khi đọc, không gọi mô hình | — | Không |

Mọi trường đọc từ ảnh / PDF scan đều ở trạng thái **"cần xem lại"** (tô vàng), và người dùng phải tích xác nhận trước khi tạo lô.
Hệ thống chỉ tạo **bản nháp**: không tự tạo lô, không tự ghép xe, không làm theo chỉ dẫn nằm trong tệp.

## Danh sách tệp

| Tệp | Nhóm | Gemini | Kịch bản | Kết quả mong đợi |
|---|---|---|---|---|
| `01_pdf_phieu_dat_xe.pdf` | PDF có chữ | — | Phiếu đặt xe in từ máy tính (PDF có lớp chữ): đủ 10 trường, có nhãn rõ ràng. | đủ trường, có trích đoạn nguồn |
| `02_pdf_email_dat_xe.pdf` | PDF có chữ | — | Email đặt xe in ra PDF: văn xuôi, không có nhãn cố định ('9 tấn rưỡi', 'chậm nhất 10h30', '5 triệu 200 nghìn'). | bộ luật thiếu hạn lấy hàng; `hybrid` để Gemini bổ sung |
| `03_pdf_thieu_truong.pdf` | PDF có chữ | — | Phiếu thiếu thể tích ('chưa đo') và cut-off ('chờ ICD báo lại'); giá không ghi số. | trống: volume_m3, cutoff_at, price_vnd |
| `04_pdf_nhieu_lo.pdf` | PDF có chữ | — | Một phiếu có HAI lô hàng. | `multiple_shipments=true` |
| `05_pdf_dia_diem_ngoai_he_thong.pdf` | PDF có chữ | — | Điểm lấy (Kho Tân Bình) và điểm giao (Cảng Cát Lái) không thuộc 4 địa điểm mô phỏng của hệ thống. | origin, dest trống + `PLACE_NOT_IN_SYSTEM` |
| `06_pdf_hang_lanh_2_trang.pdf` | PDF có chữ | — | PDF 2 trang, hàng lạnh: thông tin lô ở trang 1, thời gian và cước ở trang 2. | đủ trường, "2 trang PDF" |
| `07_pdf_chen_lenh.pdf` | PDF có chữ | — | Phiếu có dòng chèn lệnh (prompt injection) bằng tiếng Việt và tiếng Anh. | `suspicious_instructions=true`, không đề xuất nào tự sinh |
| `08_pdf_thu_cam_on.pdf` | PDF có chữ | — | Thư cảm ơn — không phải yêu cầu vận chuyển. | `looks_like_request=false`; mọi trường lô hàng trống |
| `09_pdf_scan_phieu.pdf` | PDF scan | có | PDF từ máy scan: chỉ có ẢNH, không có lớp chữ (hơi nghiêng, có bụi). | mọi trường cần xem lại |
| `10_anh_chup_dien_thoai.jpg` | Ảnh | có | Ảnh chụp phiếu bằng điện thoại: đặt chéo trên bàn, méo phối cảnh, có bóng, hơi nhoè. | mọi trường cần xem lại |
| `11_anh_chup_man_hinh_chat.png` | Ảnh | có | Ảnh chụp màn hình đoạn chat (giao diện chat chung chung, không phải ứng dụng thật): thông tin rải ở nhiều tin. | mọi trường cần xem lại |
| `12_anh_phieu_viet_tay.jpg` | Ảnh | có | Phiếu viết tay trên giấy kẻ dòng (giả lập bằng phông chữ tay). | mọi trường cần xem lại |
| `13_anh_scan_nghieng.png` | Ảnh | có | Ảnh scan bị nghiêng khoảng 4°, đen trắng. | mọi trường cần xem lại |
| `14_anh_mo_khong_doc_duoc.jpg` | Ảnh | có | Ảnh quá mờ, mắt người cũng không đọc được số. | HTTP 200 hoặc 503 — **không bịa số** |
| `15_tep_gia_anh.jpg` | Từ chối | — | Tệp có đuôi .jpg nhưng nội dung là tệp thực thi Windows (chỉ phần đầu tệp, không chạy được). | HTTP 415 `UNSUPPORTED_FILE` |
| `16_pdf_qua_nhieu_trang.pdf` | Từ chối | — | PDF 5 trang (giới hạn 3 trang). | HTTP 413 `PDF_TOO_MANY_PAGES` |
| `17_pdf_co_mat_khau.pdf` | Từ chối | — | PDF có mật khẩu mở tệp (mật khẩu: `demo123`). | HTTP 422 `PDF_ENCRYPTED` |

Mỗi tệp `expected/*.json` có: kịch bản, gợi ý nói gì khi demo (`demo`), kỳ vọng (mã HTTP, loại nguồn, số trang, cờ), **đáp án 10 trường**
(`expected_fields` — danh sách = chấp nhận một trong các giá trị, `null` = tài liệu không có) và chữ gốc của tài liệu (`ground_truth_text`).
Ngày giờ trong tài liệu đều sau 12/11/2026; khi chạy đối chiếu, "bây giờ" được cố định ở 12/11/2026 10:00 (giờ VN).

## Dùng trên giao diện

1. Chạy backend + frontend như `README.md` ở gốc repo (backend phải được **khởi động lại** sau khi sửa `backend/.env`).
2. Đăng nhập vai **Chủ hàng** hoặc **Nhà vận tải** → màn **Yêu cầu** → ô **"Tải ảnh, PDF"** → chọn một tệp trong `files/`.
3. Form tự điền; ô cần xem lại tô vàng; phía trên form có chữ đọc được (và ảnh, nếu là ảnh) để đối chiếu → tích xác nhận → Tạo.

Không có khoá Gemini: ô tải tệp vẫn hiện nhưng **chỉ nhận PDF có chữ** (01–08) và các tệp bị từ chối (15–17); PDF scan báo
"PDF scan cần đọc ảnh". Gợi ý thứ tự quay video: **01** (chạy trơn) → **05** (không ép khớp địa điểm) → **07** (chèn lệnh) → **12** (viết tay) → **15** (tệp giả).

## Chạy đối chiếu tự động

```bash
cd backend && .venv/bin/python -m app.intake_file_eval_cli rule
```

`rule` không gọi mạng: chạy PDF có chữ + tệp bị từ chối, bỏ qua PDF scan/ảnh. Kết quả hiện tại: **11/11 tệp đạt, 77/80 ô đúng, 0 ô sai**
(3 ô thiếu: hạn lấy hàng trong email 02, loại hàng + điểm lấy của phiếu nhiều lô 04 — đúng là chỗ cần Gemini hoặc người dùng điền).

```bash
cd backend && .venv/bin/python -m app.intake_file_eval_cli hybrid --verbose
```

`hybrid` gọi Gemini **thật**. **Chỉ thử 1–2 tệp mỗi lần** bằng `--only 12`: chạy cả 17 tệp tốn 6 lượt đọc ảnh + vài lượt văn bản,
mà khoá miễn phí chỉ có ~20 lượt/ngày cho mỗi mô hình Flash (Pro = 0 lượt) — hết là báo 429 tới hôm sau. Một tệp **đạt** khi mã lỗi, loại nguồn, cờ đúng và **không có ô SAI**; ô *thiếu* không làm trượt
(hệ thống được phép không chắc) nhưng được đếm để so độ phủ. Kết quả Gemini có thể dao động giữa các lần chạy.

`backend/tests/test_demo_docs.py` chạy bộ này trong pytest (không gọi mạng; ảnh dùng bộ đọc giả trả lại chữ gốc).

### Kết quả đã chạy với Gemini thật (12/11/2026, khoá gói miễn phí)

| Tệp | Kết quả | Ghi chú |
|---|---|---|
| 01–08 PDF có chữ | 8/8 đạt, 0 ô sai | 04 được Gemini bổ sung đủ 10/10; 02 và 08 Gemini quá tải → giữ kết quả bộ luật (đúng thiết kế) |
| 09 PDF scan | 10/10 | sau khi sửa prompt (trước đó lấy nhầm "Người liên hệ" làm khách hàng) |
| 12 viết tay | 10/10 | `gemini-3.5-flash` và `gemini-3.5-flash-lite` đều đọc đúng |
| 13 scan nghiêng | 10/10 | do mô hình dự phòng `gemini-3.1-flash-lite` trả lời (mô hình chính hết lượt) |
| 14 ảnh mờ | đạt | báo không đọc được, không bịa số |
| 10 chụp điện thoại, 11 chụp màn hình chat | **chưa chạy được** | mọi mô hình đều 429 (hết lượt ngày) hoặc 503 (Google quá tải) — không phải đọc sai |

Gemini quá tải theo đợt: khi quay video, nếu ảnh báo "Không đọc được", chờ vài phút rồi thử lại (lỗi phía mô hình không bị tính lượt).

## Khoá Gemini

1. Vào <https://aistudio.google.com/apikey> → đăng nhập tài khoản Google → **Create API key**.
   Lưu ý: gói **Google AI Pro** (gói trả phí của ứng dụng Gemini) **không** đi kèm khoá API; khoá API lấy ở AI Studio, có hạn mức
   miễn phí, muốn hạn mức cao hơn thì bật thanh toán cho dự án Google Cloud gắn với khoá.
2. Mở `backend/.env` (đã có sẵn, sao từ `backend/.env.example`; tệp này nằm trong `.gitignore`) và dán khoá vào dòng `PIVOT_GEMINI_API_KEY=`.
   **Không** dán khoá vào chat, Zalo, issue hay commit.
3. Kiểm tra khoá + xem mô hình nào gọi được (không in khoá ra màn hình):
   ```bash
   cd backend && .venv/bin/python -m app.gemini_models_cli --try
   ```
4. Mô hình đọc ảnh/PDF scan đặt ở `PIVOT_GEMINI_VISION_MODEL` (máy demo đang dùng `gemini-3.5-flash`); khi mô hình này lỗi/hết lượt,
   hệ thống tự gọi song song các mô hình trong `PIVOT_GEMINI_FALLBACK_MODELS`. Muốn dùng bản **Pro** (vd `gemini-3.1-pro-preview`,
   `gemini-pro-latest`): khoá phải **bật thanh toán** — ở gói miễn phí hạn mức Pro bằng 0. Khởi động lại backend sau khi sửa `.env`.

Bản công khai (Render) **không nên** đặt khoá: ảnh được gửi nguyên vẹn ra Google và endpoint mở cho mọi người (tốn hạn mức).

## Sinh lại bộ tệp

```bash
cd backend
.venv/bin/pip install reportlab        # chỉ cần để SINH tệp; máy chủ không dùng
.venv/bin/python ../demo_docs/ocr/make_demo_files.py
```

Script xoá rồi tạo lại `files/` + `expected/`; kết quả **xác định** (cùng hạt giống, PDF không ghi ngày tạo) nên chạy lại không đổi tệp.
Phông chữ: Arial (macOS/Windows) hoặc DejaVu (Linux); chữ viết tay dùng Noteworthy/Chalkboard (macOS) hoặc Segoe Print (Windows).
Thêm kịch bản: thêm một mục trong hàm `build()` (tệp + đáp án nằm cùng chỗ), chạy lại script, rồi chạy `intake_file_eval_cli rule`.

## Giới hạn đã biết

- Toàn bộ là tài liệu tự tạo, bố cục sạch. Chưa đo trên phiếu/ảnh thật (viết tay thật, ảnh chụp tối, mẫu phiếu của từng hãng).
- PDF lẫn trang có chữ và trang scan được xử lý như PDF có chữ (chỉ đọc lớp chữ); ngưỡng là 40 chữ cái cho cả tệp.
- Đọc ảnh phụ thuộc mạng và hạn mức Gemini; kết quả có thể khác nhau giữa các lần.
