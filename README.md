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

**Đăng nhập đơn giản: chỉ nhập tên + chọn vai trò** (không mật khẩu — chỉ dành cho demo). **Mỗi tab trình duyệt là MỘT người**; muốn thử nhiều bên (A, B khác nhau) thì mở thêm tab và đặt tên khác.
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
cd backend && .venv/bin/python -m pytest      # 204 test (DB test riêng: pivot_test)
cd frontend && npm test && npx tsc --noEmit
```

## Màn hình (menu hiện theo vai trò)
**Yêu cầu** (gõ tay hoặc nút *Dán tin nhắn* → bản nháp có dẫn nguồn) · **Lô / Xe / Slot** (sửa, huỷ lô) · **Ghép** (khuyến nghị + lý do; chi tiết kỹ thuật ở mục *Chi tiết*) · **Xác nhận** · **Theo dõi** (bản đồ OSM, mốc geofence, ETA P50–P90) · **Lịch dock** (Gantt, check-in/bốc dỡ, dwell) · **Ngoại lệ** (mức độ, playbook, SLA, ghép lại) · **Hành trình** (timeline, tái lập) · **Lợi ích**; chuông thông báo ở thanh đầu. Chủ hàng thấy cả 6; nhà vận tải không có *Yêu cầu* ở menu (vẫn vào được bằng nút *+ Yêu cầu*); ICD thấy *Slot · Xác nhận · Lịch dock · Theo dõi · Ngoại lệ · Hành trình*; điều phối viên thấy phần còn lại và mở *Kịch bản demo* từ menu avatar.

## Tính năng chính
- **Yêu cầu**: tạo, **sửa** (khoá lạc quan, bị khoá khi đã giữ/cam kết) và **huỷ** (xoá mềm, giữ audit); nhập từ văn bản dán → bản nháp có trích đoạn nguồn, người dùng duyệt rồi mới tạo.
- **Ghép**: hard gate trước điểm; không có phương án thì không ép ghép; đội xe của tổ chức khác được che chi tiết.
- **Booking**: hold có hạn, xác nhận theo từng bên, re-check, chống đặt trùng, `Idempotency-Key`.
- **Sự kiện**: đầu vào xe (`VEHICLE_POSITION`, `VEHICLE_AVAILABLE`) và chuyến (`TRIP_*`, `ETA_UPDATED`) idempotent qua outbox; chỉ nhà vận tải sở hữu xe được báo.
- **Theo dõi & ETA**: GPS **mô phỏng** qua đường sự kiện thật, mốc geofence một lần, ETA luật P50/P90 + ETA trực tiếp; ML trên lịch sử mô phỏng chỉ được dùng khi qua cổng promote, tự hạ về luật.
- **ETA có tín hiệu thật**: tuyến đường bộ thật (OSRM) trên bản đồ + hệ số thời tiết (Open-Meteo) cộng vào ETA luật; không có mạng thì tự hạ về luật. Biến môi trường: `PIVOT_SIGNALS_ENABLED` (mặc định `true`), `PIVOT_OSRM_URL`, `PIVOT_WEATHER_URL`, `PIVOT_SIGNALS_TIMEOUT_S`. Giao thông chỉ là hệ số luật theo khung giờ (không phải kẹt xe trực tiếp). Cần chạy `alembic upgrade head` (bảng `trip_routes`).
- **Lịch dock**: tự xếp dock khi chuyến xác nhận, chống trùng lịch, dwell time, NO_SHOW; ETA đổi chỉ *đề xuất* khung mới, ICD chấp nhận mới áp dụng.
- **Ngoại lệ**: 8 loại, mức độ theo luật có version, playbook + SLA + leo thang, thông báo mô phỏng, **ghép lại** chuyến chưa lấy hàng (hệ thống không tự đổi chuyến).
- **Lợi ích**: baseline chốt trước, estimated → measured → verified, xác minh phải do bên độc lập.

## AI nhập liệu — đọc kỹ
Mặc định dùng **bộ phân tích theo luật (không phải AI)**. Để dùng mô hình ngôn ngữ: `PIVOT_INTAKE_EXTRACTOR=llm` và `PIVOT_ANTHROPIC_API_KEY=<khoá của bạn>` (không đưa khoá vào mã/commit). Bộ LLM **chưa được chạy thử với API thật**. Dù dùng bộ nào, kết quả vẫn qua kiểm tra bằng luật và chỉ là bản nháp.
