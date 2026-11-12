# Báo cáo kiểm thử — LOGECTION prototype

Ngày chạy: 10/11/2026 · Máy: macOS (Darwin 25.6), Python 3.13.7, PostgreSQL 16 (Docker, local), Node 24.
Dữ liệu: **mô phỏng** (3 tổ chức, 5 thành viên, 10 xe, 20 lô, 20 slot). Các ngưỡng là cấu hình pilot, không phải SLA.

## Kết quả tổng
| Bộ test | Số test | Kết quả |
|---|---|---|
| Backend (pytest) | 255 | **255 đạt** (cập nhật 12/11/2026) |
| Frontend (vitest) + `tsc` + `vite build` | 31 | **31 đạt**, kiểu và build sạch (cập nhật 12/11/2026) |
| Kịch bản demo (CLI trên API thật) | 10 | **10/10 đạt** (0,1–0,8 giây mỗi kịch bản), chạy lặp lại nhiều lần đều đạt |

Theo file (backend): access 9 · benefits_audit 12 · booking 14 · events 10 · gates 11 · intake 14 · integrity 17 · match 16 · perf 1 · scenarios 12 · shipment_edit 8 · vehicle_events 6 · login 13 · login_scenarios 11 · deploy 9 · **tracking 6 · incidents 12 · docks 10 · eta 10** (mở rộng Control Tower).

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

## Gọn giao diện (đổi tên LOGECTION)
Đo bằng trình duyệt thật, cùng dữ liệu, cùng cách đo (số từ hiển thị trong `#root`, chờ nội dung ổn định); bản cũ dựng từ `HEAD` ở cổng riêng.

| Màn hình (vai trò) | Trước | Sau | Giảm |
|---|---|---|---|
| Đăng nhập | 141 | 44 | −69% |
| Thanh đầu + menu | 69 | 21 | −70% |
| Yêu cầu (Chủ hàng) | 210 | 81 | −61% |
| Lô / Xe / Slot (Chủ hàng · Nhà vận tải · ICD · Điều phối) | 483 · 654 · 276 · 935 | 203 · 146 · 106 · 368 | −58% · −78% · −62% · −61% |
| Ghép, sau khi chạy (Chủ hàng · Điều phối) | 707 · 803 | 214 · 312 | −70% · −61% |
| Xác nhận (Chủ hàng · Nhà vận tải · ICD · Điều phối) | 827 · 817 · 813 · 1398 | 230 · 249 · 418 · 469 | −72% · −70% · −49% · −66% |
| Hành trình (Chủ hàng · Điều phối) | 202 · 242 | 106 · 176 | −48% · −27% |
| Lợi ích | 283 | 100 | −65% |
| Kịch bản demo (Điều phối) | 287 | 98 | −66% |

Từ điển chữ giao diện (tiếng Việt): **2.645 → 1.364 từ (−48%)**, có test giữ ngân sách ≤ 1.400 từ và test phát hiện khoá i18n không còn dùng. Menu theo vai trò có test (ICD không vào được Ghép/Lợi ích; Demo chỉ ở menu avatar của Điều phối viên). Chi tiết kỹ thuật (điểm thành phần, điều kiện, phiên bản, tái lập) chỉ thu gọn vào mục *Chi tiết*, không xoá. Số từ giữ lại một phần là dữ liệu thật (biển số, giờ, tên lô) nên không giảm hơn nữa.

## Đăng nhập đơn giản, mỗi tab một người
- `test_login` (13 test): tên/vai trò sai → 422; người mới có tổ chức riêng + dữ liệu mẫu đúng vai trò; đăng nhập lại = cùng tài khoản (không nhân đôi dữ liệu); **hai chủ hàng tên khác nhau không đọc/sửa/huỷ được lô của nhau (404)**; luồng ghép–giữ–xác nhận **giữa ba tổ chức mới** (chủ hàng → nhà vận tải → ICD) ra `confirmed`, người ngoài không thấy đề xuất; biển số xe của các nhà vận tải không trùng; **reset giữ danh tính** và cấp lại dữ liệu mẫu; retime không dịch dữ liệu của người đăng ký; đăng nhập bị chặn ngoài chế độ mô phỏng; trần số người đăng ký; 6 lần đăng nhập đồng thời cùng tên mới → đúng một tài khoản.
- **Kịch bản demo vẫn xác định khi đã có người tự đăng nhập** (`test_login_scenarios`, 7 test): lỗi này được phát hiện khi chạy trên server thật có Hoa/Lan/Cường — họ có xe/slot riêng nên ghép có thể chọn trúng, làm 3/6 kịch bản lỗi dù test cũ xanh. Sửa: kịch bản chạy trên dữ liệu seed thuần (reset `provision=false`) rồi cấp lại dữ liệu mẫu cho người đăng ký sau khi xong (kịch bản xoá dữ liệu nghiệp vụ của mọi người, kể cả lô họ tự tạo). 6/6 đạt 2 lần liên tiếp trên server thật.
- Kiểm tra trên trình duyệt với **3 tab thật** (Hoa/Chủ hàng, Lan/Nhà vận tải, Cường/Điều hành ICD): mở tab mới thì chưa đăng nhập; cả ba lần lượt xác nhận → `confirmed`; đăng xuất ở một tab **không** ảnh hưởng tab khác; sau reset các tab vẫn đăng nhập. Màn hình đăng nhập không tràn ngang ở 375px.
- Giới hạn: **không có mật khẩu** (theo yêu cầu) nên ai biết tên + vai trò là vào được tài khoản đó; hai tên chỉ khác dấu (Hòa/Hoa) là cùng một tài khoản; nhân đôi tab trình duyệt sao chép phiên.

## Nhập liệu có dẫn nguồn (DRAFT 6.1)
- **Bộ trích xuất mặc định là bộ phân tích theo luật (regex), KHÔNG phải AI**, và giao diện/API gắn nhãn đúng như vậy.
- Bộ gọi mô hình ngôn ngữ (`LLMExtractor`, cần `PIVOT_INTAKE_EXTRACTOR=llm` + `PIVOT_ANTHROPIC_API_KEY`) **đã viết nhưng CHƯA chạy với API thật** (không có khoá). Chỉ kiểm thử bằng giả lập: dạng request, văn bản nằm trong thẻ dữ liệu và không lọt vào system prompt, lỗi/JSON hỏng → rỗng (fail closed), khoá lạ bị lọc.
- Bảo vệ không phụ thuộc bộ trích xuất nào: giá trị phải kèm **trích đoạn có thật trong văn bản** (trích đoạn bịa → bỏ); kiểm bằng luật (kiểu, đơn vị, khoảng, địa điểm khớp duy nhất, thứ tự thời gian, múi giờ); ngày tương đối ("mai") luôn yêu cầu xác nhận; trường thiếu/mơ hồ = `null` + `needs_review`, không suy đoán; chỉ dẫn trong văn bản chỉ bị gắn cờ, không thực thi (test: văn bản độc hại không tạo lô/đề xuất/xác nhận nào); chỉ lưu băm + trích đoạn, không lưu văn bản gốc.
- **Độ chính xác từng trường** trên tập đối chiếu 12 tin mẫu (`tests/fixtures/intake_cases.json`): loại hàng, trọng lượng, điểm lấy, điểm đến, 3 mốc giờ đều **12/12**, tổng **98/98**, không có giá trị sai nào mang trạng thái `ok`. ⚠️ Đây là tập hồi quy **do chính nhóm viết** nên số 100% **không** phải độ chính xác trên tin nhắn thật; cần tập đối chiếu do người dùng nghiệp vụ duyệt, và chưa đo thời gian sửa/tỷ lệ nhập thành công (DRAFT 6.1). Tập mẫu đã giúp phát hiện và sửa 2 lỗi thật của bộ phân tích (bắt nhầm "9h 11/11" thành 09:11; mượn ngày của trường kế tiếp).
- Chưa hỗ trợ PDF/ảnh/giọng nói, chỉ văn bản dán (đúng phạm vi MVP của DRAFT).

## Mở rộng Control Tower (chi tiết: `docs/CONTROL_TOWER.md`)
| # | Kịch bản mới | Kết quả | Điểm kiểm chính |
|---|---|---|---|
| 7 | Theo dõi chuyến | Đạt | GPS mô phỏng → 3 mốc geofence đúng thứ tự, mỗi mốc **một** lần; không lộ giá/khách hàng |
| 8 | Hỏng xe → ghép lại | Đạt | critical theo luật `sev-v1`, playbook + SLA, thông báo, chỉ bên có trách nhiệm hoàn tất bước, **ghép lại** trả tài nguyên, xe hỏng không bị đề xuất lại |
| 9 | Lịch dock | Đạt | tự xếp dock; ETA đổi → chỉ đề xuất, ICD chấp nhận mới áp dụng; hai yêu cầu dời cùng khung → [200, 409] |
| 10 | Mô hình ETA | Đạt | ML mô phỏng được promote (MAE −64%, độ phủ P90 88%); dữ liệu trôi → tự hạ về luật |

Test đáng chú ý: `test_no_future_leakage…` (trôi chỉ xuất hiện ở đoạn test thì độ phủ phải tụt — nếu test lọt vào huấn luyện/hiệu chỉnh thì không tụt), `test_concurrent_reschedules…`, `test_replan_guards…` (404/403/409 đúng chỗ, `CARGO_ON_BOARD`), `test_replaying_position_events…`. Lỗi tìm được khi viết test: làm tròn khung dock xuống thay vì lên (khung có thể bắt đầu sớm hơn slot vài chục giây) — đã sửa.

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
| Rà soát 12/11 | Xe `offline` (sau hỏng + ghép lại) không bao giờ trở lại `available` dù đã báo `VEHICLE_AVAILABLE` | `VEHICLE_AVAILABLE` đưa xe `offline` về `available` (xe `committed` giữ nguyên) |
| Rà soát 12/11 | `customer_name` > 200 ký tự / `price_vnd` vượt BIGINT → HTTP 500 | Ràng buộc schema → 422 |
| Rà soát 12/11 | Một lỗi trong vòng worker nền làm task asyncio chết lặng lẽ; lỗi `sweep` chặn cả xử lý outbox | `background_loop` bắt lỗi + log; mỗi việc dọn một transaction riêng |
| Rà soát 12/11 | Đăng nhập tên mới gặp lỗi ràng buộc khác race vẫn trả khoá của người dùng không tồn tại; biển số sinh chỉ 16^4 khả năng | Ném lại lỗi thật; biển số 7 ký tự hex |
| Rà soát 12/11 | `/v1/tracking` LIMIT 100 trước khi lọc quyền → chuyến cũ của người dùng biến mất; `/v1/benefits` nạp cả sổ rồi lọc | Lọc quyền trong SQL |
| Rà soát 12/11 | Giao diện: `useData` để phản hồi chậm của token/chuyến cũ ghi đè dữ liệu mới; đổi chuyến phải đợi nhịp polling | Chỉ áp dụng lần gọi mới nhất; tải ngay khi đổi `key` |

## Giới hạn đã biết (không che giấu)
- Mọi số liệu là **mô phỏng**; "verified" chỉ chứng minh quy trình ghi sổ/xác minh độc lập, **không** chứng minh tiết kiệm thật. Lợi ích mới có một hạng mục (km chạy rỗng × đơn giá phẳng, baseline hằng số 38 km); chưa có chi phí chờ/bốc dỡ/đi vòng, chưa có Bảng A/B/C của DRAFT 11.3.
- **AI thật chưa được kiểm chứng**: bộ mặc định là luật; bộ LLM chưa chạy với API thật.
- ETA luật có P50/P90 nhưng tham số là mô phỏng; ML chỉ huấn luyện trên lịch sử **do nhóm sinh** (chưa có dữ liệu thật); ghép vẫn theo từng lô độc lập (chưa có phân bổ nhiều xe–hàng, OR-Tools là P1).
- Sửa yêu cầu chưa xoá được giá/khách hàng đã nhập (để trống = giữ nguyên). Bản nháp nhập liệu dùng lại được cho nhiều lô.
- Ghép lại chỉ với chuyến chưa lấy hàng; đường đi GPS là nội suy mô phỏng; dock/ICD mới có 2 dock cố định 30′; SMS/email chỉ là nhật ký giả lập; chưa làm cold chain, returns, emissions, dashboard KPI tổng (xem `docs/CONTROL_TOWER.md`).
- `external_id_map`, `logistics_units`, `shipment_legs` mới là khung bảng (chưa có logic ánh xạ ID đối tác, gộp/tách hàng); `ID_UNRESOLVED` chưa được sinh ra; chưa có API sửa sự kiện (`corrects_event_id`).
- `proposal.confirmed` là xác nhận mock (chưa có API ICD thật); đăng nhập là token dev; chưa RLS, telemetry, backup/restore, staging, CI.
