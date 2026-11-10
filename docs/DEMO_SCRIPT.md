# Kịch bản video demo (≈ 4 phút) — PIVOT / VSGA

Theo DRAFT mục 12: mỗi màn hình trả lời một câu hỏi kinh doanh. Dữ liệu **mô phỏng** — nói rõ điều này ngay đầu video.

**Chuẩn bị (30 giây trước khi quay):** `docker compose up -d` · `python -m app.seed` · mở backend + frontend · mở http://127.0.0.1:5173 · giữ tiếng Việt (có thể bật EN ở cuối).

| Thời gian | Màn hình / vai | Việc làm | Câu hỏi kinh doanh & lời dẫn gợi ý |
|---|---|---|---|
| 0:00–0:20 | Toàn cảnh | Chỉ huy hiệu **● MÔ PHỎNG** + bộ chọn 5 thành viên | "Đây là prototype một hành lang KCN–ICD, dữ liệu mô phỏng. Mỗi thành viên là một vai thật: chủ hàng, vận tải, ICD, điều phối." |
| 0:20–1:00 | **1 · Nhập yêu cầu** (Nguyên) | **Dán một tin nhắn** → *Trích xuất bản nháp* (chỉ ra trích đoạn nguồn, ô *cần xem lại*, nhãn "không phải AI") → *Dùng bản nháp* → tick xác nhận → tạo lô; sang **2 · Xe & hàng**, bấm **Sửa** rồi **Huỷ yêu cầu** | "Hệ thống chỉ tạo bản nháp có dẫn nguồn, trường thiếu hoặc ngày tương đối đều bắt người dùng xác nhận; yêu cầu thiếu trường không thành lô hợp lệ. Sửa được khi chưa giữ/cam kết; huỷ là xoá mềm để giữ vết. Chủ hàng thấy giá của mình; chuyển sang Phú — giá bị ẩn." (chứng minh phân quyền) |
| 1:00–2:00 | **3 · Khuyến nghị** (Nguyên) | Chọn `LOT-A-001` → **Chạy ghép**; mở "Xe bị loại"; sau đó chọn `LOT-A-008` | "Hard gate chạy trước, chỉ xe đạt mới có điểm. Xe thiếu tải, sai hàng, dữ liệu quá hạn bị loại kèm mã lý do. Lô cut-off sát: hệ thống nói *không có phương án khả thi*, không ép ghép. Điểm ưu tiên tách riêng khỏi số tiền tiết kiệm; ETA ghi rõ rule-based." |
| 2:00–3:00 | **4 · Xác nhận** (Nguyên → Minh → Khôi) | Nguyên **Giữ slot** (đếm ngược 120s) → đổi vai Minh **Xác nhận** → Nguyên **Xác nhận** → Khôi **Xác nhận** | "Hệ thống chỉ đề xuất; mỗi bên xác nhận phần của mình, nút chỉ bật khi đúng quyền. Slot là *mock*, không phải đặt chỗ thật." (có thể mở 2 tab: Nguyên và Phước bấm giữ cùng lúc → chỉ một thành công) |
| 3:00–3:40 | **5 · Timeline** (Minh) | Mở chuyến → **Bắt đầu chuyến** → **ETA trễ 30 phút** → đổi vai Nguyên quyết định ngoại lệ | "ETA đổi trên chuyến đã cam kết: hệ thống *không tự đổi xe*, chỉ tạo ngoại lệ để người quyết định. Mỗi dòng có người thực hiện, thời điểm, độ trễ dữ liệu." |
| 3:40–4:20 | **6 · Lợi ích** (Minh → Nguyên) | Minh **Hoàn tất** chuyến → mở **Lợi ích** → chọn dòng → Nguyên **Xác minh** (nhà vận tải không tự xác minh được) | "Baseline chốt trước khi biết kết quả. Ba mức tách riêng: ước tính, đã đo, đã xác minh — chỉ số đã xác minh mới đáng tin. Từ con số tới bằng chứng và giả định." |
| 4:20–4:40 | **Tái lập** (Timeline) | Bấm **Tái lập** | "Quyết định tái lập được từ dữ liệu đã lưu, kèm phiên bản quy tắc/giả định." |
| 4:40–5:00 | **7 · Kịch bản demo** (Phú) | **Chạy cả 6** → 6/6 đạt | "Sáu kịch bản bắt buộc chạy lặp lại được, gồm gửi trùng 10 lần và worker khởi động lại." |

**Lưu ý khi quay:** bấm **Làm mới dữ liệu demo** (vai Phú) ngay trước khi quay vì vị trí xe quá 5 phút bị loại; nếu cần sạch hoàn toàn dùng `python -m app.seed`. Slide thuyết trình (DRAFT mục 12: kiến trúc, AI, matching, governance, kinh tế, roadmap) là phần riêng, không nằm trong repo này.
