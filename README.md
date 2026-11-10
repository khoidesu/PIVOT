# PIVOT / VSGA — prototype điều phối logistics

Dự án dự thi **AI FOR BUSINESS INNOVATION**. Prototype chạy được cho một luồng quyết định:
xe sắp trống → hàng sẵn sàng → kiểm tra khả thi (hard gate) → giữ slot → xác nhận → theo dõi → ghi nhận lợi ích.

> ⚠️ **Mọi dữ liệu trong bản demo là MÔ PHỎNG** (gắn nhãn *MÔ PHỎNG / mock* trên giao diện). Slot ICD là slot giả lập, không phải đặt chỗ thật.

- Nội dung cốt lõi / kế hoạch: [`DRAFT.md`](DRAFT.md) (bất biến) · định hướng kỹ thuật & tiến trình: [`CLAUDE.md`](CLAUDE.md)
- Báo cáo kiểm thử: [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) · kịch bản video demo: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)

## Công nghệ
React + TypeScript + Vite · FastAPI + Pydantic · SQLAlchemy + Alembic · PostgreSQL 16 (Docker) · worker đọc outbox trong PostgreSQL.
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

Bộ chọn vai trò ở thanh trên: **Nguyên / Phước** (Chủ hàng, tổ chức A) · **Minh** (Nhà vận tải, tổ chức B) · **Khôi** (Điều hành ICD, tổ chức C) · **Phú** (Điều phối viên).
Đăng nhập là token dev cho prototype local (`Authorization: Bearer dev:<user>`); backend vẫn kiểm tra tổ chức + quyền ở mọi API.

### Đưa demo về trạng thái chuẩn
| Việc | Cách |
|---|---|
| Làm mới mốc thời gian (vị trí xe quá 5 phút là bị loại) | nút **Làm mới dữ liệu demo** (vai Phú) hoặc `python -m app.seed --retime` |
| Reset toàn bộ (xoá đề xuất, sự kiện, sổ lợi ích) | `python -m app.seed` hoặc `POST /v1/demo/reset` (vai Phú) |
| Chạy 6 kịch bản demo | tab **7 · Kịch bản demo** (vai Phú) hoặc `python -m app.demo.run_scenarios` |

## Kiểm thử
```bash
cd backend && .venv/bin/python -m pytest      # 126 test (DB test riêng: pivot_test)
cd frontend && npm test && npx tsc --noEmit
```

## 7 màn hình
1. Nhập yêu cầu (gõ tay hoặc dán tin nhắn → bản nháp có dẫn nguồn; **sửa/huỷ** ở màn 2) · 2. Xe & hàng · 3. Khuyến nghị + lý do · 4. Xác nhận & slot · 5. Timeline & ngoại lệ · 6. Lợi ích · 7. Kịch bản demo

## Tính năng chính
- **Yêu cầu**: tạo, **sửa** (khoá lạc quan, bị khoá khi đã giữ/cam kết) và **huỷ** (xoá mềm, giữ audit); nhập từ văn bản dán → bản nháp có trích đoạn nguồn, người dùng duyệt rồi mới tạo.
- **Ghép**: hard gate trước điểm; không có phương án thì không ép ghép; đội xe của tổ chức khác được che chi tiết.
- **Booking**: hold có hạn, xác nhận theo từng bên, re-check, chống đặt trùng, `Idempotency-Key`.
- **Sự kiện**: đầu vào xe (`VEHICLE_POSITION`, `VEHICLE_AVAILABLE`) và chuyến (`TRIP_*`, `ETA_UPDATED`) idempotent qua outbox; chỉ nhà vận tải sở hữu xe được báo.
- **Lợi ích**: baseline chốt trước, estimated → measured → verified, xác minh phải do bên độc lập.

## AI nhập liệu — đọc kỹ
Mặc định dùng **bộ phân tích theo luật (không phải AI)**. Để dùng mô hình ngôn ngữ: `PIVOT_INTAKE_EXTRACTOR=llm` và `PIVOT_ANTHROPIC_API_KEY=<khoá của bạn>` (không đưa khoá vào mã/commit). Bộ LLM **chưa được chạy thử với API thật**. Dù dùng bộ nào, kết quả vẫn qua kiểm tra bằng luật và chỉ là bản nháp.
