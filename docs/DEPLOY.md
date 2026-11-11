# Triển khai công khai (Render) — LOGECTION

Mục tiêu: một **link duy nhất** để mọi người cùng dùng (giao diện + API chung một địa chỉ), dữ liệu **mô phỏng**.

> ✅ Đã kiểm thử trên máy: build image Docker, chạy container với DB trống (migration → seed lần đầu → phục vụ giao diện), mã quản trị, khởi động lại giữ nguyên dữ liệu, kịch bản đạt trong container (nay là 10; image lớn hơn vì có numpy + scikit-learn, đo thực tế 716 MB — cân nhắc RAM/đĩa của gói miễn phí; đã chạy thử container với DB trống: migration + seed + `/healthz` + ML ETA + 10/10 kịch bản).
> ⚠️ **Chưa deploy thật lên Render** (cần tài khoản của bạn). File `render.yaml` viết theo tài liệu Render nhưng chưa được Render kiểm tra; nếu lần đầu báo lỗi cấu hình, xem mục "Sự cố thường gặp".

## Những gì được triển khai
- 1 web service Docker (`Dockerfile`): React build + FastAPI + worker nền chạy cùng tiến trình.
- 1 PostgreSQL do Render quản lý. Khi khởi động: `alembic upgrade head` → seed **chỉ khi DB trống** (các lần sau không đụng dữ liệu người dùng).
- Biến môi trường (đặt sẵn trong `render.yaml`): `PIVOT_DATABASE_URL` (tự lấy từ DB), `PIVOT_ADMIN_KEY` (Render tự sinh), `PIVOT_DATA_MODE=mock`.

## Các bước (bạn làm — cần đăng nhập, tôi không làm thay được)
1. **Đẩy mã lên GitHub** `khoidesu/PIVOT` (nhánh `main`) — Render lấy mã từ đây.
2. Vào <https://dashboard.render.com> → đăng nhập (có thể bằng GitHub) → **New → Blueprint**.
3. Cho Render quyền đọc repo `khoidesu/PIVOT` → chọn repo → Render đọc `render.yaml` → **Apply**.
4. Chờ build 5–10 phút. Xong có địa chỉ dạng `https://pivot-xxxx.onrender.com`.
5. Lấy mã quản trị: service **pivot → Environment → `PIVOT_ADMIN_KEY`** (bấm hiện giá trị). **Chỉ giữ cho bạn** hoặc người phụ trách demo.
6. Mở địa chỉ → đăng nhập bằng tên + vai trò. Muốn Reset/Chạy kịch bản: chọn **Phú — Điều phối viên** → tab **7 · Kịch bản demo** → nhập mã quản trị.

### Kiểm tra sau khi deploy
```bash
URL=https://pivot-xxxx.onrender.com
curl -s $URL/healthz                                        # {"status":"ok"}
curl -s -H "Authorization: Bearer dev:shipper_a" $URL/v1/meta   # có "admin_key_required": true
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Authorization: Bearer dev:dispatch" $URL/v1/demo/reset   # phải là 403 khi không có mã
```
Rồi mở giao diện, chạy tab Demo với mã quản trị: kỳ vọng **10/10 kịch bản đạt**.

## Ai làm được gì khi công khai (đọc kỹ)
| Việc | Ai làm được |
|---|---|
| Xem, chọn vai trò, tạo/sửa/huỷ yêu cầu, ghép, giữ slot, xác nhận… | **Bất kỳ ai có link** (đăng nhập là token dev: ai cũng chọn được thành viên) |
| Reset dữ liệu, chạy kịch bản, làm tuổi dữ liệu, chạy worker thủ công | Chỉ vai Điều phối viên **và** có mã quản trị |
| Dữ liệu | Mô phỏng, dùng chung: người này sửa thì người khác thấy; có thể bị người khác thay đổi. Cần sạch thì Reset |

Rủi ro còn lại, đã chấp nhận cho bản demo: không có xác thực thật (OIDC), không giới hạn tần suất (rate limit), `/docs` mở công khai, ai cũng có thể thêm/sửa dữ liệu mô phỏng. **Không dùng cho dữ liệu thật.**
**Không đặt `PIVOT_ANTHROPIC_API_KEY` trên bản công khai** (endpoint nhập liệu mở, có thể bị lạm dụng làm tốn tiền); mặc định dùng bộ phân tích theo luật, không tốn gì.

## Giới hạn của gói miễn phí (kiểm tra điều khoản Render hiện hành)
- Service có thể **tự ngủ** khi lâu không có truy cập → lần mở đầu chậm (có thể vài chục giây); worker nền tạm dừng khi ngủ và chạy tiếp khi thức.
- DB miễn phí có thể **hết hạn/giới hạn dung lượng** sau một thời gian; trước buổi chấm điểm nên mở trước để đánh thức và kiểm tra bằng bộ lệnh ở trên.
- Muốn không ngủ/không hết hạn: nâng gói trả phí.

## Vận hành
- **Cập nhật:** đẩy mã mới lên `main` → Render tự build và deploy lại (migration tự chạy khi khởi động).
- **Đưa demo về trạng thái chuẩn:** tab Demo (Phú + mã quản trị) → *Làm mới dữ liệu demo*, hoặc `POST /v1/demo/reset` kèm `X-Admin-Key`.
- **Xem log:** Render → service pivot → Logs.
- **Gỡ bỏ:** Render → xoá service `pivot` và database `pivot-db`.

## Chạy thử container trên máy (giống hệt bản deploy)
```bash
docker compose up -d                       # Postgres local
docker compose exec -T db psql -U pivot -d postgres -c 'CREATE DATABASE pivot_deploy'
docker build -t pivot:local .
docker run --rm -p 127.0.0.1:18000:8000 --network <tên-mạng-compose> \
  -e PIVOT_DATABASE_URL=postgres://pivot:pivot_dev@db:5432/pivot_deploy -e PIVOT_ADMIN_KEY=doi-ma-nay pivot:local
# mở http://127.0.0.1:18000
```

## Sự cố thường gặp
| Triệu chứng | Cách xử lý |
|---|---|
| Blueprint báo sai cấu hình | Kiểm tra tên trường trong `render.yaml` theo tài liệu Render hiện hành, hoặc tạo tay: Web Service (Docker, root là repo) + PostgreSQL, rồi đặt 3 biến môi trường ở trên |
| Build lỗi `npm ci` | Cần `frontend/package-lock.json` đã commit |
| Mở link báo 502/đang khởi động | Service đang thức dậy hoặc đang chạy migration; chờ rồi tải lại; xem Logs |
| Không kết nối được DB | `PIVOT_DATABASE_URL` phải trỏ tới DB của Render (internal URL); mã tự đổi `postgres://` → `postgresql+psycopg://` |
| Tab Demo báo cần mã quản trị | Nhập đúng `PIVOT_ADMIN_KEY`; mã chỉ lưu trong tab đang mở |


## Đăng nhập đơn giản (tên + vai trò)
Bản demo công khai dùng đăng nhập **không mật khẩu**: ai cũng nhập được tên + vai trò, kể cả *Điều phối viên*. Đã giảm rủi ro bằng: trần số người đăng ký (`MAX_REGISTERED_USERS = 500` trong `backend/app/accounts.py`, vượt thì 429); tên chỉ cho 2–40 ký tự an toàn; chỉ chạy khi `PIVOT_DATA_MODE=mock`; reset/kịch bản/làm tuổi dữ liệu vẫn cần **mã quản trị** (`PIVOT_ADMIN_KEY`). **Không dùng cho dữ liệu thật.** Mỗi người mới tạo một tổ chức + dữ liệu mẫu nhỏ nên cơ sở dữ liệu sẽ lớn dần theo số người đăng nhập; reset toàn bộ giữ danh tính, muốn xoá hẳn thì dọn bảng `users/organizations` có `is_registered = true`.

## Phương án đang dùng: Render + Neon
Xem [`DEPLOY_RENDER_NEON.md`](DEPLOY_RENDER_NEON.md). (Phương án Hugging Face Spaces đã bỏ vì Docker Space chuyển sang gói trả phí.)
