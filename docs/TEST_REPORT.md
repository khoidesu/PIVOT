# Báo cáo kiểm thử — PIVOT / VSGA prototype

Ngày chạy: 10/11/2026 · Máy: macOS (Darwin 25.6), Python 3.13.7, PostgreSQL 16 (Docker, local), Node 24.
Dữ liệu: **mô phỏng** (3 tổ chức, 5 thành viên, 10 xe, 20 lô, 20 slot). Các ngưỡng là cấu hình pilot, không phải SLA.

## Kết quả tổng
| Bộ test | Số test | Kết quả |
|---|---|---|
| Backend (pytest) | 126 | **126 đạt** |
| Frontend (vitest) + `tsc` + `vite build` | 7 | **7 đạt**, kiểu và build sạch |
| Kịch bản demo (CLI trên API thật) | 6 | **6/6 đạt** (0,2–1,2 giây mỗi kịch bản), chạy lặp lại nhiều lần đều đạt |

Theo file (backend): access 9 · benefits_audit 12 · booking 14 · events 10 · gates 11 · intake 14 · integrity 17 · match 16 · perf 1 · scenarios 8 · shipment_edit 8 · vehicle_events 6.

## Đối chiếu điều kiện nghiệm thu (CLAUDE.md mục 8 / DRAFT bảng 3, 5)
| Nhóm | Mục tiêu | Bằng chứng | Kết quả |
|---|---|---|---|
| Tính đúng quyết định | 100% case hard gate quan trọng qua test | thiếu tải, sai loại hàng, trễ giờ, cut-off, quá hạn dữ liệu (xe **và lô**), slot đầy/**sai ICD**/trễ khung giờ, thiếu dữ liệu → UNKNOWN, FAIL ưu tiên hơn UNKNOWN | Đạt |
| Không gán tài nguyên trùng | Hai request đồng thời → chỉ 1 thành công | 6 hold cùng đề xuất → 1×200 + 5×409; 2 đề xuất cùng xe → [200, 409]; chỗ slot cuối → [200, 409]; **sửa lô + giữ chỗ cùng lúc → [200, 409], không deadlock**; partial unique index | Đạt |
| Sự kiện | Gửi lặp 10 lần chỉ 1 tác động | 10 lần → 1×202 + 9×200; worker chết giữa chừng → áp dụng đúng 1 lần; tin muộn không kéo lùi; **sự kiện vị trí xe cũ hơn dữ liệu hiện có → `late`** | Đạt |
| **Nguồn dữ liệu đúng chủ thể** | Số đo/vị trí/ETA chỉ do nhà vận tải sở hữu xe báo | chủ hàng, node, điều phối viên báo sự kiện chuyến → 403; payload sai (km âm/quá lớn/chuỗi, delay không phải số, sự kiện từ tương lai) → 422 ngay khi nhận, không để lại job lỗi | Đạt |
| Phân quyền | Không truy cập trái phép giữa tổ chức | đọc/ghi chéo tổ chức → 404; giá + khách hàng chỉ chủ lô; **sửa/huỷ chỉ chủ lô** (điều phối viên 403); mã lô unique theo tenant | Đạt |
| **Tối thiểu hoá dữ liệu** | Đề xuất chỉ hiện dữ liệu đủ dùng | chủ hàng thấy xe bị loại với biển số đã che + mã lý do + dữ kiện của lô mình; **không** thấy tải trọng/tuổi vị trí/loại hàng chở được của đội xe khác; điều phối viên và chủ xe thấy đủ | Đạt |
| Re-check trước xác nhận | Trong cùng transaction | vị trí xe quá hạn ngay trước xác nhận cuối → `RECHECK_FAILED`, `cancelled`, giải phóng holds | Đạt |
| Lợi ích | Baseline chốt trước; tách mức; **xác minh độc lập** | đổi giả định sau khi ghép không đổi baseline; ước tính không xác minh được; bên báo số đo **không** tự xác minh (403); forwarder tự chở lô của mình → dừng ở `measured` (409) | Đạt |
| Tái lập | Quyết định tái lập được | `replay` tính lại điểm từ dữ liệu đã lưu; sửa điểm → phát hiện | Đạt |
| Ngoại lệ | Không tự sửa chuyến đã cam kết | ETA đổi: trạng thái, xe, version không đổi + ngoại lệ; đề xuất chưa cam kết → hết hiệu lực | Đạt |
| **Sửa/huỷ yêu cầu** | Không sửa lặng lẽ chuyến đã cam kết | sửa có khoá lạc quan; làm mới `data_updated_at`; vô hiệu đề xuất cũ; bị chặn khi đã giữ/cam kết (`SHIPMENT_LOCKED`); huỷ là xoá mềm giữ audit; vết audit chỉ ghi tên trường, không ghi giá/khách hàng | Đạt |
| **Nhập liệu có dẫn nguồn** | Chỉ bản nháp; trường thiếu → needs_review; văn bản là dữ liệu không tin cậy | xem mục "Nhập liệu" bên dưới | Đạt (với giới hạn nêu rõ) |
| Hiệu năng | Match P95 < 2 s cho 20 xe × 50 lô | `test_perf`: **p50 = 50 ms, p95 = 93 ms, max = 241 ms** (50 lượt qua HTTP + DB local; số đo thay đổi theo tải máy, lần chạy trước 30 ms). Danh sách đề xuất: 15 đề xuất → **8 truy vấn** (trước 79) | Đạt |

## Nhập liệu có dẫn nguồn (DRAFT 6.1)
- **Bộ trích xuất mặc định là bộ phân tích theo luật (regex), KHÔNG phải AI**, và giao diện/API gắn nhãn đúng như vậy.
- Bộ gọi mô hình ngôn ngữ (`LLMExtractor`, cần `PIVOT_INTAKE_EXTRACTOR=llm` + `PIVOT_ANTHROPIC_API_KEY`) **đã viết nhưng CHƯA chạy với API thật** (không có khoá). Chỉ kiểm thử bằng giả lập: dạng request, văn bản nằm trong thẻ dữ liệu và không lọt vào system prompt, lỗi/JSON hỏng → rỗng (fail closed), khoá lạ bị lọc.
- Bảo vệ không phụ thuộc bộ trích xuất nào: giá trị phải kèm **trích đoạn có thật trong văn bản** (trích đoạn bịa → bỏ); kiểm bằng luật (kiểu, đơn vị, khoảng, địa điểm khớp duy nhất, thứ tự thời gian, múi giờ); ngày tương đối ("mai") luôn yêu cầu xác nhận; trường thiếu/mơ hồ = `null` + `needs_review`, không suy đoán; chỉ dẫn trong văn bản chỉ bị gắn cờ, không thực thi (test: văn bản độc hại không tạo lô/đề xuất/xác nhận nào); chỉ lưu băm + trích đoạn, không lưu văn bản gốc.
- **Độ chính xác từng trường** trên tập đối chiếu 12 tin mẫu (`tests/fixtures/intake_cases.json`): loại hàng, trọng lượng, điểm lấy, điểm đến, 3 mốc giờ đều **12/12**, tổng **98/98**, không có giá trị sai nào mang trạng thái `ok`. ⚠️ Đây là tập hồi quy **do chính nhóm viết** nên số 100% **không** phải độ chính xác trên tin nhắn thật; cần tập đối chiếu do người dùng nghiệp vụ duyệt, và chưa đo thời gian sửa/tỷ lệ nhập thành công (DRAFT 6.1). Tập mẫu đã giúp phát hiện và sửa 2 lỗi thật của bộ phân tích (bắt nhầm "9h 11/11" thành 09:11; mượn ngày của trường kế tiếp).
- Chưa hỗ trợ PDF/ảnh/giọng nói, chỉ văn bản dán (đúng phạm vi MVP của DRAFT).

## 6 kịch bản demo bắt buộc
| # | Kịch bản | Kết quả | Điểm kiểm chính |
|---|---|---|---|
| 1 | Ghép thành công | Đạt | ghép → hold → 3 bên xác nhận → completed → ghi sổ `measured` → **chủ hàng (độc lập) xác minh** |
| 2 | Xe không tương thích bị loại | Đạt | CAPACITY_EXCEEDED, CARGO_INCOMPATIBLE, DATA_STALE, VEHICLE_UNAVAILABLE; xe bị loại không được chấm điểm; không có phương án → không ép ghép |
| 3 | Dữ liệu quá hạn | Đạt | vị trí +10 phút → mọi xe DATA_STALE; **nhà vận tải gửi sự kiện `VEHICLE_POSITION` → ghép lại được (không cần reset)** |
| 4 | Hai người cùng giữ một tài nguyên | Đạt | Nguyên + Phước giữ đồng thời → [200, 409], slot 4 → 3 |
| 5 | ETA đổi → ngoại lệ | Đạt | chuyến cam kết giữ nguyên + ngoại lệ; đề xuất chưa cam kết hết hiệu lực |
| 6 | Sự kiện trùng / worker restart | Đạt | 10 lần chỉ 1 tác động; crash + restart → áp dụng đúng 1 lần |

## Lỗi tìm được và đã sửa
| Phát hiện bởi | Lỗi | Xử lý |
|---|---|---|
| Review lần 2 (chạy script) | Chủ hàng tự báo `TRIP_COMPLETED` với `actual_empty_km = -500` rồi tự xác minh → "verified" 7,5 triệu ₫ bịa; node/điều phối viên cũng báo được sự kiện chuyến | Phân quyền sự kiện theo loại + validate payload + xác minh độc lập |
| Review lần 2 | Chủ hàng thấy chi tiết đội xe của nhà vận tải khác | Che chi tiết (bản đầy đủ vẫn lưu để audit) |
| Review lần 2 | `ETA_UPDATED` với `delay_minutes="abc"` làm job lỗi/retry | Validate khi nhận (422) |
| Review lần 2 | 79 truy vấn cho 15 đề xuất; GET ghi DB | Dựng theo lô (8 truy vấn); GET không ghi, worker dọn hold hết hạn |
| Review lần 2 | Không có đầu vào event-driven cho xe (vị trí/khả dụng); dữ liệu không bao giờ "tươi" lại | `VEHICLE_POSITION`, `VEHICLE_AVAILABLE` idempotent, chống tin cũ |
| Yêu cầu người dùng | Chỉ thêm được yêu cầu, chưa sửa/xoá | `PATCH`/`DELETE` có khoá lạc quan, khoá khi đã giữ/cam kết |
| Chạy tab Demo | Reset bằng `TRUNCATE` bế tắc với worker nền | `DELETE` theo thứ tự khoá ngoại + test hồi quy (bản cũ làm test treo) |
| Chạy tab Demo | Endpoint chạy kịch bản tự chờ chính giao dịch của mình | Nhả giao dịch trước khi chạy |
| Review lần 1 | Hold hết hạn chiếm tài nguyên (index không dùng được `now()`) | Hết hạn trong transaction + worker |

## Giới hạn đã biết (không che giấu)
- Mọi số liệu là **mô phỏng**; "verified" chỉ chứng minh quy trình ghi sổ/xác minh độc lập, **không** chứng minh tiết kiệm thật. Lợi ích mới có một hạng mục (km chạy rỗng × đơn giá phẳng, baseline hằng số 38 km); chưa có chi phí chờ/bốc dỡ/đi vòng, chưa có Bảng A/B/C của DRAFT 11.3.
- **AI thật chưa được kiểm chứng**: bộ mặc định là luật; bộ LLM chưa chạy với API thật.
- ETA là rule-based (đường chim bay × 1,3), chưa có khoảng bất định P50/P90; ghép vẫn theo từng lô độc lập (chưa có phân bổ nhiều xe–hàng, OR-Tools là P1).
- Sửa yêu cầu chưa xoá được giá/khách hàng đã nhập (để trống = giữ nguyên). Bản nháp nhập liệu dùng lại được cho nhiều lô.
- `request_replan` của ngoại lệ chỉ ghi nhận quyết định; chưa có luồng huỷ/lập lại chuyến đã cam kết.
- `external_id_map`, `logistics_units`, `shipment_legs` mới là khung bảng (chưa có logic ánh xạ ID đối tác, gộp/tách hàng); `ID_UNRESOLVED` chưa được sinh ra; chưa có API sửa sự kiện (`corrects_event_id`).
- `proposal.confirmed` là xác nhận mock (chưa có API ICD thật); đăng nhập là token dev; chưa RLS, telemetry, backup/restore, staging, CI.
