# Báo cáo kiểm thử — PIVOT / VSGA prototype

Ngày chạy: 10/11/2026 · Máy: macOS (Darwin 25.6), Python 3.13.7, PostgreSQL 16 (Docker, local), Node 24.
Dữ liệu: **mô phỏng** (seed: 3 tổ chức, 5 thành viên, 10 xe, 20 lô, 20 slot). Các ngưỡng là cấu hình pilot, không phải SLA.

## Kết quả tổng
| Bộ test | Số test | Kết quả |
|---|---|---|
| Backend (pytest) | 93 | **93 đạt** |
| Frontend (vitest) | 5 | **5 đạt** (khoá i18n VI/EN khớp, mọi reason_code có template) |
| Kịch bản demo (CLI trên API thật) | 6 | **6/6 đạt**, mỗi kịch bản 0,1–0,4 giây, chạy lặp lại 2 lần liên tiếp đều đạt |

Các test chạy nhiều lần liên tiếp (kể cả race condition) không flaky.

## Đối chiếu điều kiện nghiệm thu (CLAUDE.md mục 8 / DRAFT bảng 3, 5)
| Nhóm | Mục tiêu | Bằng chứng | Kết quả |
|---|---|---|---|
| Tính đúng quyết định | 100% case hard gate quan trọng qua test | `test_gates` (11), `test_match` (14): thiếu tải, sai loại hàng, trễ giờ, cut-off, quá hạn dữ liệu (xe + lô), slot đầy/sai ICD, thiếu dữ liệu → UNKNOWN, FAIL ưu tiên hơn UNKNOWN | Đạt |
| Không gán tài nguyên trùng | Hai request đồng thời → chỉ 1 thành công | `test_booking`: 6 hold cùng đề xuất → 1×200 + 5×409; 2 đề xuất cùng xe → [200, 409]; chỗ slot cuối → [200, 409], `remaining` không âm; ràng buộc DB (partial unique index) chặn đặt trùng | Đạt |
| Sự kiện | Gửi lặp 10 lần chỉ 1 tác động; replay không tạo tác động ngoài | `test_events`, kịch bản 6: 10 lần → 1×202 + 9×200 duplicate; worker chết giữa chừng → không tác động nửa vời, restart áp dụng đúng 1 lần (version v3 → v4) | Đạt |
| Tin muộn | Không kéo trạng thái lùi | TRIP_STARTED sau completed → `late`, trạng thái giữ nguyên; TRIP_COMPLETED trước START → `invalid` | Đạt |
| Phân quyền | Không truy cập trái phép giữa tổ chức A/B | `test_access` (9): list/GET theo id/ghi chéo tổ chức → 404; giá + khách hàng chỉ chủ lô; điều phối viên không thấy giá; node không thấy lô/tiền; lô mã trùng giữa tenant không lộ sự tồn tại | Đạt |
| Chống nhầm lẫn quyền xác nhận | Quyền xác nhận thuộc chủ thể | carrier nhận việc, shipper duyệt lô, node duyệt slot; điều phối viên giữ được slot nhưng KHÔNG accept/xác minh/quyết định ngoại lệ | Đạt |
| Re-check trước xác nhận | Kiểm tra lại trong cùng transaction | vị trí xe quá hạn ngay trước xác nhận cuối → `RECHECK_FAILED`, đề xuất `cancelled`, holds được giải phóng | Đạt |
| Lợi ích | Baseline chốt trước quyết định; tách estimated/measured/verified | `test_benefits_audit`: đổi giả định sau khi ghép không làm đổi baseline đã chốt; ước tính không xác minh được (409); gửi lại TRIP_COMPLETED không nhân đôi (unique) | Đạt |
| Tái lập | Quyết định tái lập được | `replay` tính lại điểm từ dữ liệu đã lưu = điểm đã lưu; sửa điểm → phát hiện không tái lập | Đạt |
| Ngoại lệ | Không tự sửa chuyến đã cam kết | ETA đổi trên chuyến cam kết: trạng thái, xe, version không đổi + tạo ngoại lệ; đề xuất chưa cam kết → hết hiệu lực | Đạt |
| Hiệu năng | Match P95 < 2 s cho 20 xe × 50 lô | `test_perf`: **p50 = 23 ms, p95 = 30 ms, max = 48 ms** (50 lượt, qua HTTP + DB local, không có API ngoài) | Đạt |

## 6 kịch bản demo bắt buộc
| # | Kịch bản | Kết quả | Điểm kiểm chính |
|---|---|---|---|
| 1 | Ghép thành công | Đạt | ghép → hold → 3 bên xác nhận → completed → ghi sổ `measured` (532.000 ₫ mô phỏng) → verified |
| 2 | Xe không tương thích bị loại | Đạt | CAPACITY_EXCEEDED, CARGO_INCOMPATIBLE, DATA_STALE, VEHICLE_UNAVAILABLE; xe bị loại không được chấm điểm; không có phương án → "không có phương án khả thi" |
| 3 | Dữ liệu quá hạn | Đạt | tuổi vị trí +10 phút → mọi xe DATA_STALE → không đề xuất; dữ liệu tươi → ghép được |
| 4 | Hai người cùng giữ một tài nguyên | Đạt | Nguyên + Phước giữ đồng thời → [200, 409], slot 4 → 3 |
| 5 | ETA đổi → ngoại lệ | Đạt | chuyến cam kết giữ nguyên + ngoại lệ; đề xuất chưa cam kết hết hiệu lực để tính lại |
| 6 | Sự kiện trùng / worker restart | Đạt | 10 lần chỉ 1 tác động; crash + restart → áp dụng đúng 1 lần; timeline chỉ có 1 sự kiện |

Chạy lại: `cd backend && .venv/bin/python -m app.demo.run_scenarios` (cần backend đang chạy), hoặc tab **Kịch bản demo** trên giao diện.

## Lỗi tìm được trong quá trình kiểm thử (đã sửa)
- Reset bằng `TRUNCATE` bế tắc (deadlock) với worker nền/request song song → đổi sang `DELETE` theo thứ tự khoá ngoại; có test hồi quy (với bản cũ test treo).
- Endpoint chạy kịch bản tự chờ chính giao dịch của mình → nhả giao dịch trước khi chạy.
- Hold hết hạn chiếm tài nguyên vì partial unique index không dùng được `now()` → hết hạn lười trong transaction.
- Xem lịch sử các lỗi review ở `CLAUDE.md` mục 10.

## Giới hạn đã biết (không che giấu)
- Mọi số liệu là **mô phỏng**; lợi ích "verified" ở đây chỉ chứng minh quy trình ghi sổ/xác minh, **không** chứng minh tiết kiệm thật.
- ETA là rule-based (đường chim bay × 1,3 + bảng thời gian cố định), độ tin cậy thấp, đã gắn nhãn trên UI; chưa có ML.
- `proposal.confirmed` là xác nhận mock (chưa có API ICD thật); đăng nhập là token dev, chưa OIDC.
- Chưa làm (P1 theo DRAFT): AI nhập liệu có dẫn nguồn, OR-Tools phân bổ nhiều xe–hàng, ETA ML có benchmark.
- Chưa kiểm thử tải đồng thời lớn, backup/restore, staging từ xa (demo chạy local).
