# Triển khai miễn phí: Neon (Postgres) + Hugging Face Spaces — LOGECTION

Kết quả: **một link công khai chạy 24/7**, dữ liệu **được giữ** sau mỗi lần khởi động lại (nằm ở Neon). Dữ liệu vẫn là **mô phỏng**.

> ✅ Đã kiểm thử trên máy: dựng đúng gói sẽ đẩy lên Space (`deploy/hf/push_space.sh` ở chế độ DRY_RUN), build image, chạy ở cổng 7860 với DB trống → `/healthz` OK, không có `X-Frame-Options`, 10/10 kịch bản đạt.
> ⚠️ **Chưa chạy thật trên Hugging Face/Neon** (cần tài khoản của bạn). Điều kiện gói free của hai dịch vụ hay đổi — đối chiếu trang chính thức.

## Phần 1 — Neon (database)
1. Vào <https://neon.tech> → đăng ký (có thể bằng GitHub/Google).
2. **Create project**: tên `logection`, Postgres version 16 hoặc mới hơn, vùng gần bạn (vd *Singapore*). Database mặc định `neondb` là được.
3. Ở trang project → **Connect** (hoặc *Connection details*):
   - Tắt công tắc **Connection pooling** (lấy chuỗi **trực tiếp**, host *không* có `-pooler`) — worker nền dùng khoá dòng nên không hợp với pooler giao dịch.
   - Copy chuỗi dạng `postgresql://USER:PASSWORD@ep-xxx.REGION.aws.neon.tech/neondb?sslmode=require`.
4. **Giữ chuỗi này bí mật** (là mật khẩu DB): chỉ dán vào mục Secrets của Hugging Face ở Phần 2, không đưa vào chat/commit.

Ghi chú: ứng dụng tự đổi `postgresql://` sang driver đúng, tự chạy migration và tự seed khi DB trống. Worker nền truy vấn mỗi giây nên Neon **không tự ngủ**; gói free tính theo giờ tính toán mỗi tháng — chạy 24/7 nhiều tuần có thể chạm hạn mức, nên kiểm tra mục *Usage* của Neon. Với demo vài ngày thì thường ổn.

## Phần 2 — Hugging Face Space
1. Đăng ký/đăng nhập <https://huggingface.co>.
2. **New → Space**: tên `logection`, **SDK: Docker** → *Blank*, hardware **CPU basic (free)**, Visibility **Public** (để ban giám khảo vào không cần tài khoản). Create.
3. Vào Space → **Settings → Variables and secrets** → thêm 2 **Secrets**:
   - `PIVOT_DATABASE_URL` = chuỗi Neon ở Phần 1.
   - `PIVOT_ADMIN_KEY` = một chuỗi ngẫu nhiên dài (tạo bằng `openssl rand -hex 16`); chỉ người phụ trách demo biết.
4. Tạo **Access token**: <https://huggingface.co/settings/tokens> → New token → loại *Write* → copy (chỉ hiện một lần).
5. Trên máy, ở thư mục gốc repo, chạy (thay bằng tài khoản và tên Space của bạn):
   ```bash
   deploy/hf/push_space.sh TAI-KHOAN/logection
   ```
   Khi git hỏi *Username*: tên tài khoản HF; *Password*: **dán access token** (tự gõ ở terminal).
   Script lấy mã ở commit `HEAD`, thêm README cấu hình Space, cố định cổng 7860 và bật `PIVOT_ALLOW_FRAMING` rồi đẩy lên Space. **Hãy commit mọi thay đổi trước khi chạy.**
6. Mở Space → tab **Logs** xem build (5–10 phút, lâu hơn do scikit-learn). Khi thấy `Uvicorn running` là xong.
7. Link công khai dạng `https://TAI-KHOAN-logection.hf.space`.

## Phần 3 — Kiểm tra
```bash
URL=https://TAI-KHOAN-logection.hf.space
curl -s $URL/healthz                                                       # {"status":"ok"}
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Authorization: Bearer dev:dispatch" $URL/v1/demo/reset   # 403 khi không có mã
```
Mở link → đăng nhập **Phú — Điều phối viên** → menu avatar → *Kịch bản demo* → nhập `PIVOT_ADMIN_KEY` → **Chạy tất cả** → kỳ vọng 10/10 đạt. Sau đó bấm **Làm mới dữ liệu demo** để trả dữ liệu sạch trước buổi trình bày.

Kiểm tra giữ dữ liệu: tạo một lô → ở Space chọn **Settings → Factory reboot** (hoặc *Restart*) → lô vẫn còn.

## Cập nhật sau này
Sửa mã → `git commit` → chạy lại `deploy/hf/push_space.sh TAI-KHOAN/logection`. Migration mới tự chạy khi khởi động; dữ liệu cũ giữ nguyên.

## Sự cố thường gặp
| Triệu chứng | Cách xử lý |
|---|---|
| Space báo *Runtime error* / *Build failed* hết bộ nhớ | xem Logs; thử Factory reboot; nếu vẫn lỗi dùng Render (xem `DEPLOY.md`) |
| Log: `could not connect` / `SSL` | kiểm tra chuỗi Neon còn đủ `?sslmode=require`, và là chuỗi **trực tiếp** (không `-pooler`) |
| Lần mở đầu chậm vài giây | Neon đánh thức DB sau thời gian nhàn rỗi, hoặc Space vừa được đánh thức |
| Space "Sleeping" | không có truy cập nhiều ngày; mở link để đánh thức (mất ~1 phút) |
| Nhúng trong trang huggingface.co bị trắng | dùng thẳng link `*.hf.space` |
| `git push` bị từ chối | token phải là loại **Write**; tên Space đúng dạng `tai-khoan/ten-space` |

## Lưu ý an toàn
- Dùng **tài khoản/ DB riêng cho demo**; không đặt dữ liệu thật.
- Đừng đặt `PIVOT_ANTHROPIC_API_KEY` trên bản công khai. Mã quản trị chỉ chia sẻ khi cần.
- Nếu lộ chuỗi Neon hoặc token: đổi mật khẩu DB (Neon → Roles → Reset password) và thu hồi token ở HF Settings.
