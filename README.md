# LOGECTION — prototype điều phối logistics

> **Tên dự án: LOGECTION** (trước đây PIVOT / VSGA). Chỉ phần nhìn thấy được đổi tên; biến môi trường `PIVOT_*`, tên cơ sở dữ liệu, dịch vụ Docker/Render và repo `khoidesu/PIVOT` giữ nguyên để không làm hỏng triển khai. `DRAFT.md` (bất biến) vẫn gọi là PIVOT / VSGA.

Dự án dự thi **AI FOR BUSINESS INNOVATION**. Prototype chạy được cho một luồng quyết định:
xe sắp trống → hàng sẵn sàng → kiểm tra khả thi (hard gate) → giữ slot → xác nhận → theo dõi → ghi nhận lợi ích.

> ⚠️ **Mọi dữ liệu trong bản demo là MÔ PHỎNG** (gắn nhãn *MÔ PHỎNG / mock* trên giao diện). Slot ICD là slot giả lập, không phải đặt chỗ thật.

- Nội dung cốt lõi / kế hoạch: [`DRAFT.md`](DRAFT.md) (bất biến) · định hướng kỹ thuật & tiến trình: [`CLAUDE.md`](CLAUDE.md)
- Mở rộng Control Tower (theo dõi, ETA, lịch dock, ngoại lệ): [`docs/CONTROL_TOWER.md`](docs/CONTROL_TOWER.md)
- Triển khai công khai (Render, một link): [`docs/DEPLOY.md`](docs/DEPLOY.md) · Báo cáo kiểm thử: [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) · kịch bản video demo: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)

## Công nghệ
React + TypeScript + Vite (+ Leaflet / OpenStreetMap) · FastAPI + Pydantic · SQLAlchemy + Alembic · PostgreSQL 16 (Docker) · worker đọc outbox trong PostgreSQL · numpy + scikit-learn (ETA mô phỏng).
Chạy hoàn toàn trên máy local (không CI/CD, không staging từ xa).

## Chạy local

Yêu cầu: Docker, Python 3.13, Node 20+.

```bash
# 1) Cơ sở dữ liệu (cổng 5433, chỉ bind 127.0.0.1)
docker compose up -d

# 2) Backend (lần đầu: tạo venv + cài thư viện)
cd backend
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed                       # dữ liệu mô phỏng chuẩn
.venv/bin/uvicorn app.main:app --port 8000         # worker nền chạy cùng API

# 3) Frontend (terminal khác)
cd frontend && npm install && npm run dev          # mở http://127.0.0.1:5173
```

**Đăng nhập đơn giản: chỉ nhập tên + chọn vai trò** (không mật khẩu — chỉ dành cho demo). **Một trang, nhiều người:** thanh dọc bên trái liệt kê từng người; bấm **+** để thêm (4 người của nhóm bấm một lần, hoặc "Mở cả chuỗi ba bên", hoặc tên khác để có bên A, B khác nhau). Mỗi người là một cửa sổ riêng (lưới / cột / tập trung, kéo để đổi chỗ, thu nhỏ vẫn chạy nền, số đỏ là việc đang chờ). Tối đa 8 người; bản cũ "mỗi tab một người" không còn cần thiết.
- Vai trò: **Chủ hàng**, **Nhà vận tải**, **Điều hành ICD**, **Điều phối viên**.
- Tên tự đặt. Cùng tên + cùng vai trò = cùng một tài khoản; **tên mới = tổ chức riêng + dữ liệu mẫu mô phỏng** (chủ hàng 4 lô, nhà vận tải 4 xe, ICD 8 slot), nên hai tab chủ hàng tên khác nhau là hai công ty tách biệt và ghép chéo được với nhau.
- Tài khoản mẫu có sẵn (kịch bản demo/test dùng): **Nguyên, Phước** (Chủ hàng, tổ chức A) · **Minh** (Nhà vận tải, B) · **Khôi** (Điều hành ICD, C) · **Phú** (Điều phối viên) — đăng nhập đúng tên + vai trò đó thì vào các tài khoản này.
- Đóng tab hoặc bấm **Đăng xuất / Đổi người** để thoát; backend vẫn kiểm tra tổ chức + quyền ở mọi API (token `Authorization: Bearer dev:<khoá>`).
- Nút reset toàn bộ (tab Kịch bản demo) **giữ danh tính** người đã đăng nhập và cấp lại dữ liệu mẫu cho họ; nút *Làm mới dữ liệu demo* chỉ làm tươi dữ liệu seed.

### Đưa demo về trạng thái chuẩn
| Việc | Cách |
|---|---|
| Làm mới mốc thời gian (vị trí xe quá 5 phút là bị loại) | nút **Làm mới dữ liệu demo** (vai Phú) hoặc `python -m app.seed --retime` |
| Reset toàn bộ (xoá đề xuất, sự kiện, sổ lợi ích) | `python -m app.seed` hoặc `POST /v1/demo/reset` (vai Phú) |
| Chạy 10 kịch bản demo | menu avatar → **Kịch bản demo** (vai Điều phối viên) hoặc `python -m app.demo.run_scenarios` |

## Kiểm thử
```bash
cd backend && .venv/bin/python -m pytest      # 351 test (DB test riêng: pivot_test)
cd frontend && npm test && npx tsc --noEmit
```
**Dữ liệu ETA mô phỏng để huấn luyện ngoài (Kaggle):** `cd backend && .venv/bin/python -m app.eta_data_gen [--no-drift]` sinh `data/eta/` (CSV + schema + tham số + hướng dẫn); notebook `data/eta/eta_train_kaggle.ipynb` huấn luyện P50/P90 bằng PyTorch rồi xuất `eta_model.onnx` + `eta_model_card.json`. Đặc tả: `docs/ETA_DATASET_SPEC.md`. Model ONNX đã huấn luyện (bản **không drift**, qua cổng promote; bản có drift của Kaggle lưu ở `backend/model/archive_drift/`; dữ liệu tương ứng `data/eta_nodrift/`) đặt ở `backend/model/` (`eta_model.onnx` + `eta_model_card.json`) và **được backend nạp** bằng `onnxruntime`: chỉ dùng khi mã băm + hợp đồng đặc trưng khớp **và** qua cổng promote (giảm MAE ≥15% so với baseline mạnh nhất, độ phủ P90 ∈ [0,85; 0,97]); lỗi/không đạt → ETA luật. `PIVOT_ETA_MODEL_DIR` (đặt rỗng để tắt), `PIVOT_ETA_MODEL_FORCE=true` (ép dùng khi cổng KHÔNG đạt — chỉ để thử/demo, luôn gắn nhãn "bật thủ công"). Hard gate vẫn chỉ dùng P50 của luật. **Hướng dẫn test tính năng ETA có model: [`docs/test.md`](docs/test.md)** (12 kịch bản + kết quả mong đợi).

**ETA Sandbox** (công cụ nội bộ để thử/tinh chỉnh ETA trước khi chốt demo, không cần bật server/DB): `cd backend && .venv/bin/python -m app.eta_sandbox_cli [--only drift|scenarios|signals] [--fresh]` in 3 bảng (quét độ trôi ML · lưới kịch bản theo khung giờ · sức khoẻ OSRM/Open-Meteo/Mapbox). Tương đương qua API (vai Điều phối viên, cần mã quản trị nếu có): `GET /v1/eta/sandbox/drift-sweep`, `/scenarios`, `/signals-health?fresh=true`.

## Màn hình (menu hiện theo vai trò)
**Yêu cầu** (gõ tay hoặc nút *Dán tin nhắn* → bản nháp có dẫn nguồn) · **Lô / Xe / Slot** (sửa, huỷ lô) · **Ghép** (khuyến nghị + lý do; chi tiết kỹ thuật ở mục *Chi tiết*) · **Xác nhận** · **Theo dõi** (bản đồ OSM, mốc geofence, ETA P50–P90) · **Lịch dock** (Gantt, check-in/bốc dỡ, dwell) · **Ngoại lệ** (mức độ, playbook, SLA, ghép lại) · **Hành trình** (timeline, tái lập) · **Lợi ích**; chuông thông báo ở thanh đầu. Chủ hàng thấy cả 6; nhà vận tải không có *Yêu cầu* ở menu (vẫn vào được bằng nút *+ Yêu cầu*); ICD thấy *Slot · Xác nhận · Lịch dock · Theo dõi · Ngoại lệ · Hành trình*; điều phối viên thấy phần còn lại và mở *Kịch bản demo* từ menu avatar.

## Tính năng chính
- **Yêu cầu**: tạo, **sửa** (khoá lạc quan, bị khoá khi đã giữ/cam kết) và **huỷ** (xoá mềm, giữ audit); nhập từ văn bản dán → bản nháp có trích đoạn nguồn, người dùng duyệt rồi mới tạo.
- **Ghép**: hard gate trước điểm; không có phương án thì không ép ghép; đội xe của tổ chức khác được che chi tiết.
- **Booking**: hold có hạn, xác nhận theo từng bên, re-check, chống đặt trùng, `Idempotency-Key`.
- **Sự kiện**: đầu vào xe (`VEHICLE_POSITION`, `VEHICLE_AVAILABLE`) và chuyến (`TRIP_*`, `ETA_UPDATED`) idempotent qua outbox; chỉ nhà vận tải sở hữu xe được báo.
- **Theo dõi & ETA**: GPS **mô phỏng** qua đường sự kiện thật, mốc geofence một lần, ETA luật P50/P90 + ETA trực tiếp; ML trên lịch sử mô phỏng chỉ được dùng khi qua cổng promote, tự hạ về luật.
- **ETA có tín hiệu thật**: tuyến đường bộ thật (OSRM) trên bản đồ + hệ số thời tiết (Open-Meteo) cộng vào ETA luật; không có mạng thì tự hạ về luật. Biến môi trường: `PIVOT_SIGNALS_ENABLED` (mặc định `true`), `PIVOT_OSRM_URL`, `PIVOT_WEATHER_URL`, `PIVOT_SIGNALS_TIMEOUT_S`. Giao thông mặc định là hệ số luật theo khung giờ; đặt `PIVOT_MAPBOX_TOKEN` (khoá Mapbox, **chỉ qua biến môi trường, không commit**) để dùng **kẹt xe thật** (Mapbox Directions `driving-traffic`, làm mới ~2 phút/chuyến, có lớp màu mức kẹt trên bản đồ). Không có khoá / lỗi API → tự dùng hệ số luật. Cần chạy `alembic upgrade head` (bảng `trip_routes`).
- **Lịch dock**: tự xếp dock khi chuyến xác nhận, chống trùng lịch, dwell time, NO_SHOW; ETA đổi chỉ *đề xuất* khung mới, ICD chấp nhận mới áp dụng.
- **Ngoại lệ**: 8 loại, mức độ theo luật có version, playbook + SLA + leo thang, thông báo mô phỏng, **ghép lại** chuyến chưa lấy hàng (hệ thống không tự đổi chuyến).
- **Lợi ích**: baseline chốt trước, estimated → measured → verified, xác minh phải do bên độc lập.

## AI nhập liệu — đọc kỹ
Mặc định dùng **bộ phân tích theo luật (không phải AI)**. Có hai cách bật mô hình ngôn ngữ (đặt trong `backend/.env`, đã `.gitignore`, **không commit khoá**):

- **Gemini kết hợp luật (khuyến nghị):** `PIVOT_INTAKE_EXTRACTOR=hybrid` + `PIVOT_GEMINI_API_KEY=<khoá>`. Luật chạy trước; **chỉ khi còn thiếu/mơ hồ trường bắt buộc** mới hỏi Gemini phần còn thiếu (luật đã đủ thì không tốn lượt). Giá và tên khách: luật trích được thì **bị che** trước khi gửi; luật bỏ sót mà tin có nhắc "giá/cước/khách/KH" thì Gemini trích thêm (đoạn chữ đó vốn đã nằm trong tin gửi). Prompt kèm **bảng lịch 8 ngày** (để hiểu "thứ Sáu"). Gemini thỉnh thoảng trả chậm 30–60 giây nên có **gọi song song mô hình dự phòng** sau `PIVOT_GEMINI_HEDGE_AFTER_S=5` giây (`PIVOT_GEMINI_FALLBACK_MODELS=gemini-3.5-flash-lite`, rỗng = tắt), tổng chờ tối đa `PIVOT_GEMINI_TIMEOUT_S=25`. Mô hình mặc định `gemini-3.1-flash-lite` (đổi bằng `PIVOT_GEMINI_MODEL`; model `gemini-2.5-flash` đã ngừng cấp cho khoá mới). Giới hạn lượt gọi (vượt → tự dùng bộ luật, giao diện báo rõ): `PIVOT_LLM_PER_USER_DAY=50`, `PIVOT_LLM_PER_USER_MINUTE=5`, `PIVOT_LLM_GLOBAL_DAY=500` (đếm trong bộ nhớ tiến trình).
- **Claude:** `PIVOT_INTAKE_EXTRACTOR=llm` + `PIVOT_ANTHROPIC_API_KEY=<khoá>` (bộ này **chưa chạy thử với API thật**).

- **Kiểm tra bằng bộ tin mẫu:** `cd backend && PYTHONPATH=. .venv/bin/python -m app.intake_eval_cli [rule|hybrid] [tệp] [--quiet]` in từng trường (trạng thái, trích đoạn, ghi chú) cho `data/mock_zalo_messages.txt`; `hybrid` gọi Gemini thật (tốn lượt).
- **Đọc ảnh (nút *Tải ảnh* ở màn Yêu cầu):** dùng chung khoá Gemini, bật tự động khi có `PIVOT_GEMINI_API_KEY` (tắt bằng `PIVOT_INTAKE_IMAGE_ENABLED=false`). Trình duyệt thu nhỏ ảnh (≤1600px, JPEG) và loại EXIF; máy chủ kiểm tra loại tệp theo nội dung (JPEG/PNG/WebP), kích thước ≤4 MB, gỡ EXIF lần nữa. Gemini trả các trường + **bản phiên âm**; trích đoạn kiểm theo bản phiên âm; trường Gemini bỏ sót được bộ luật điền từ bản phiên âm. **Mọi trường từ ảnh đều ở trạng thái "cần xem lại"** cho tới khi đo được độ chính xác trên ảnh thật. Giới hạn riêng: `PIVOT_LLM_IMAGE_PER_USER_DAY=3`, `..._PER_USER_MINUTE=2`, `PIVOT_LLM_IMAGE_GLOBAL_DAY=100` — hết lượt là báo lỗi rõ (không có bộ luật để quay về); lỗi phía Gemini không tính lượt. Ảnh được gửi **nguyên vẹn** (không che được giá/tên khách), không lưu ảnh gốc.

- **Đọc PDF (cùng ô *Tải ảnh, PDF*):** PDF **có lớp chữ** (in từ Word/Excel/email) được lấy chữ **ngay trong máy chủ** (pypdfium2) rồi đi cùng đường với tin nhắn dán (luật + Gemini nếu `hybrid`) — **không cần khoá, không tốn lượt ảnh, tệp không rời máy chủ**. PDF **scan** (không có lớp chữ, ngưỡng `PIVOT_INTAKE_PDF_MIN_LETTERS=40` chữ cái) được vẽ từng trang thành JPEG (bỏ metadata/JavaScript/đính kèm) rồi đọc như ảnh (cần khoá, 1 lượt ảnh/tệp). Từ chối trước khi đọc: > `PIVOT_INTAKE_PDF_MAX_PAGES=3` trang, > `PIVOT_INTAKE_PDF_MAX_BYTES` (5 MB), có mật khẩu, hỏng. Endpoint `POST /v1/intake/drafts/file` (PDF hoặc ảnh, loại tệp theo nội dung); `/drafts/image` giữ cho tương thích. Mô hình đọc ảnh/PDF scan có thể tách riêng: `PIVOT_GEMINI_VISION_MODEL` (vd bản Pro). Mẫu cấu hình: `backend/.env.example`; kiểm tra khoá + liệt kê mô hình: `cd backend && .venv/bin/python -m app.gemini_models_cli --try`.
- **Bộ tệp demo PDF/ảnh: [`demo_docs/ocr/`](demo_docs/ocr/README.md)** — 17 tệp mô phỏng (PDF có chữ, PDF scan, ảnh chụp, viết tay, chụp màn hình chat, tệp giả/quá trang/có mật khẩu) + đáp án; chấm tự động: `cd backend && .venv/bin/python -m app.intake_file_eval_cli [rule|hybrid]`.

Dù dùng bộ nào, kết quả vẫn qua kiểm tra bằng luật (trích đoạn nguồn phải có thật, địa điểm phải khớp danh sách, thứ tự giờ, ngày tương đối luôn hỏi lại) và chỉ là bản nháp để người dùng duyệt.

**Bản web công khai (Render) dùng chung một khoá Gemini:** dán khoá vào Dashboard → Environment → `PIVOT_GEMINI_API_KEY` (đã khai báo `sync: false` trong `render.yaml`, không bao giờ ghi vào repo). Khoá chỉ nằm ở máy chủ: trình duyệt không nhận được khoá dưới bất kỳ hình thức nào (kể cả thông báo lỗi). Giới hạn lượt để nhiều người thử cùng lúc không làm cạn khoá: theo **tài khoản**, theo **IP** (đổi tên đăng nhập không có thêm lượt; sau proxy Render cần `PIVOT_TRUST_PROXY=true` — đã đặt sẵn) và **toàn hệ thống mỗi ngày + mỗi phút**: ảnh/PDF scan `PIVOT_LLM_IMAGE_PER_USER_DAY=3`, `…_PER_USER_MINUTE=2`, `PIVOT_LLM_IMAGE_PER_IP_DAY=20`, `…_PER_IP_MINUTE=6`, `PIVOT_LLM_IMAGE_GLOBAL_MINUTE=10`, `PIVOT_LLM_IMAGE_GLOBAL_DAY=100`; văn bản `PIVOT_LLM_PER_IP_DAY=150`, `PIVOT_LLM_PER_IP_MINUTE=15`, `PIVOT_LLM_GLOBAL_MINUTE=30` (0 = tắt). Văn bản hết lượt → tự dùng bộ luật; ảnh hết lượt → báo rõ. Ảnh được gửi nguyên vẹn sang Google — chỉ dùng tài liệu mô phỏng khi demo.
