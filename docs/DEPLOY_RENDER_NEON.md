# Triển khai miễn phí: Render (web) + Neon (Postgres) + UptimeRobot (giữ thức)

> Lý do chọn: Hugging Face đã chuyển Docker Space sang gói trả phí (chỉ Static miễn phí).
> Đo thực tế: container dùng **~141 MiB lúc rảnh, ~148 MiB sau khi chạy 10 kịch bản** (giới hạn thử 512 MiB, không OOM) → vừa gói Render free.
> ⚠️ Chưa chạy thật trên Render. Điều kiện gói free của Render/Neon/UptimeRobot hay đổi — đối chiếu trang chính thức.

## Các bước
1. **Neon**: đã có project + chuỗi kết nối **trực tiếp** (host không `-pooler`, có `sslmode=require`).
2. **Push mã lên GitHub** (`git push origin main`).
3. **Render**: <https://dashboard.render.com> → đăng nhập bằng GitHub → **New → Blueprint** → chọn repo `khoidesu/PIVOT` → Render đọc `render.yaml`.
4. Render hỏi giá trị cho biến `PIVOT_DATABASE_URL` → dán chuỗi Neon → **Apply**. Ứng dụng cũng nhận tên tương thích `PIVOT_DB_URL` nếu đã tạo biến này thủ công. (`PIVOT_ADMIN_KEY` tự sinh, xem ở service → Environment.)
5. Chờ build 5–10 phút → link dạng `https://logection-xxxx.onrender.com`.
6. **Giữ thức 24/7**: Render free ngủ sau ~15 phút không truy cập. Vào <https://uptimerobot.com> → Add New Monitor → HTTP(s) → URL `https://logection-xxxx.onrender.com/healthz` → interval 5 phút. (Một service chạy liên tục ≈ 744 giờ/tháng, nằm trong hạn mức giờ free hiện hành của một workspace; nếu có nhiều service free khác thì có thể vượt.)
7. Kiểm tra: mở link → đăng nhập **Phú — Điều phối viên** → menu avatar → Kịch bản demo → nhập `PIVOT_ADMIN_KEY` → Chạy tất cả (kỳ vọng 10/10 khi web và DB cùng vùng Singapore).

## Lưu ý
- Chạy kịch bản **từ máy xa** (vd máy ở VN qua Neon Singapore) rất chậm (15–37 giây/kịch bản) và có thể làm 3/10 kịch bản lỗi do worker nền xen vào các bước chờ; chạy ngay trên web đã deploy (cùng vùng với DB) thì nhanh.
- Worker nền truy vấn mỗi giây nên Neon không tự ngủ; theo dõi *Usage* của Neon (giờ tính toán free hàng tháng).
- Dữ liệu nằm ở Neon: restart/redeploy không mất. Muốn sạch: nút *Làm mới dữ liệu demo*.
- `autoDeploy: true`: mỗi push lên `main` là deploy. Đổi thành `false` nếu muốn kiểm soát.

## Giữ Neon trong hạn mức gói miễn phí (14/11/2026)
- Sự cố: Neon trả `Your account or project has exceeded the quota` → mọi API lỗi 500. Nguyên nhân: worker nền truy vấn DB **mỗi giây, 24/7**; UptimeRobot giữ Render thức nên worker không bao giờ dừng → Neon không bao giờ tạm nghỉ.
- Đã sửa trong mã: worker chỉ chạy khi có request API (`/v1/...`); rảnh quá `PIVOT_WORKER_IDLE_AFTER_S` (mặc định 120 giây) thì đóng kết nối DB và ngủ tới request kế tiếp. `/healthz` (UptimeRobot, Render) **không** đánh thức worker và không chạm DB → Neon tự tạm nghỉ sau ~5 phút không ai dùng web.
- Vẫn tốn giờ tính toán khi có người mở web (mỗi cửa sổ polling vài giây một lần); tab trình duyệt ẩn thì ngừng polling.
- Khi đã hết hạn mức: chờ Neon đặt lại hạn mức theo chu kỳ, nâng gói, hoặc tạo project Neon mới rồi dán chuỗi kết nối mới vào Render → `PIVOT_DATABASE_URL` (khởi động sẽ tự chạy migration + seed vì DB trống; dữ liệu cũ là mô phỏng).

