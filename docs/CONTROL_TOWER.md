# LOGECTION — mở rộng Control Tower (chức năng 1, 2, 3, 5)

Căn cứ: brief `docs/Đề-Xuất-Mô-Hình-Smart-Logistics-Control-Tower.pdf`. Lý do mở rộng: bản trước chỉ là lớp **ghép nối** (xe–lô–slot); nhóm thêm 4 chức năng giám sát/điều phối để có điểm nhấn riêng. `DRAFT.md` vẫn là nội dung cốt lõi bất biến; các chức năng này đi **trên** luồng lõi (hard gate → hold → xác nhận → thực hiện → lợi ích), không thay thế nó.

> ⚠️ Mọi toạ độ GPS, đường đi, lịch sử ETA, dock, SMS/email là **MÔ PHỎNG** và được gắn nhãn trên giao diện. Bản đồ dùng nền OpenStreetMap thật, nhưng vị trí xe là giả lập.

## Ánh xạ brief → hiện thực
| # | Chức năng brief | Trạng thái | Thực hiện |
|---|---|---|---|
| 1 | Tracking & Tracing | **Làm** | `VEHICLE_POSITION` có `lat/lng/speed` (validate trong hành lang); vệt `trip_tracks`; mốc geofence `ASSIGNED → AT_PICKUP → DEPARTED_PICKUP → AT_ICD_GATE → COMPLETED` suy từ vị trí, sinh sự kiện hệ thống `MILESTONE_REACHED` idempotent (mỗi mốc một lần); bộ giả lập GPS (`app/sim/gps.py`) phát tin qua đúng đường nhận sự kiện thật; màn **Theo dõi** (Leaflet + OSM) |
| 2 | ETA Prediction | **Làm** | ETA luật có **P50/P90** theo khung giờ (`assume-v2`); ETA trực tiếp từ tốc độ **quan sát** của vệt GPS (xe đứng yên → `stalled`, không bịa ETA); cờ mềm `cutoff_risk_p90`; **ML mô phỏng** (GradientBoosting phân vị) có cổng promote + tự hạ về luật |
| 3 | Truck Appointment | **Làm** | `docks`, `dock_appointments`; tự xếp dock khi chuyến `confirmed`; chống trùng lịch bằng khoá dock + kiểm tra chồng lấn (và ràng buộc loại trừ `btree_gist` nếu DB cho phép); `GATE_CHECK_IN`, `UNLOAD_STARTED`, `UNLOAD_COMPLETED` → dwell time; `NO_SHOW`; **đề xuất dời lịch khi ETA đổi — ICD chấp nhận mới áp dụng**; màn **Lịch dock** (Gantt) |
| 5 | Exception Management | **Làm** | 8 loại ngoại lệ; mức độ theo **luật có version** (`sev-v1`); playbook (bước tự động + bước do người quyết, `pb-v1`); SLA + leo thang; thông báo in-app + nhật ký SMS/email **giả lập**; `POST /v1/proposals/{id}/replan` (đóng ngõ cụt "ghép lại"); màn **Ngoại lệ** + chuông |
| 4 | Cold chain | **Không làm** | DRAFT cũng hoãn (cần cảm biến + dữ liệu nhiệt độ thật) |
| 6 | Returns / reverse logistics | **Không làm** | ngoài phạm vi prototype |
| 7 | Emissions | **Không làm** | cần hệ số phát thải có nguồn; chưa có dữ liệu |
| 8 | KPI Dashboard | **Không làm** | chỉ có KPI dock (công suất, hàng đợi, dwell, no-show) trong màn Lịch dock; chưa có dashboard tổng |

## Nguyên tắc giữ nguyên
- **Event-driven, idempotent**: mọi tín hiệu mới (vị trí, sự cố, hàng hư, check-in, bốc dỡ) đi qua `POST /v1/events` → outbox → worker; gửi lặp/worker restart không nhân đôi tác động (ngoại lệ có `dedupe_key`, mốc có unique theo chuyến+mốc).
- **Con người quyết**: hệ thống **đề xuất** (khung dock mới, ghép lại, bước playbook) và nhắc; không tự đổi xe/chuyến/lịch đã cam kết. Mỗi bước chỉ **bên chịu trách nhiệm** hoàn tất; điều phối viên không làm thay đối tác.
- **Hard gate giữ nguyên ngữ nghĩa**: gate dùng P50 như trước; P90 chỉ cho cảnh báo mềm (`cutoff_risk_p90`, `DELAY_RISK`).
- **Nhãn trung thực**: ETA luật ghi "rule-based, độ tin cậy thấp"; ML ghi "lịch sử mô phỏng — chưa chứng minh độ chính xác thật".

## Phân quyền & che dữ liệu
- Tracking/dock/ngoại lệ/thông báo chỉ hiện cho bên liên quan (chủ lô, nhà vận tải, ICD) và điều phối viên; truy cập trái phép theo id trả **404**. Không có giá/khách hàng trong Tracking/thông báo.
- Chủ hàng/nhà vận tải chỉ thấy lịch hẹn dock **của mình**; khung của người khác hiện là khối "bận" ẩn danh.
- `UNLOAD_*` chỉ do ICD (node) của slot báo; `GATE_CHECK_IN`/`INCIDENT_REPORTED`/`ETA_UPDATED` chỉ do nhà vận tải sở hữu xe; `MILESTONE_REACHED` chỉ hệ thống sinh ra (gửi từ ngoài → 422).

## ETA — chi tiết trung thực
- **Baseline luật**: P50 = deadhead + transit (như trước, để gate không đổi quyết định); khung giờ (thường / cao điểm sáng / cao điểm chiều / đêm) chỉ nới **P90**.
- **ETA trực tiếp**: quãng còn lại ÷ tốc độ quan sát từ các điểm vệt gần nhất (không tin `speed_kmh` tự khai).
- **ML (scikit-learn)**: lịch sử sinh xác định (seed cố định), chia **theo thời gian** [fit | hiệu chỉnh P90 | test] — không xáo trộn. Chỉ **promote** khi giảm MAE ≥ 15% **và** độ phủ P90 trong [0,85; 0,97]; lỗi/độ phủ tụt → **tự hạ về luật**. Mặc định (không trôi) kết quả mẫu: MAE luật 15,7′ → ML 5,7′ (−64%), độ phủ P90 88% → promote; chèn trôi 15% → độ phủ 23% → hạ về luật. Vì lịch sử do chính nhóm sinh ra, kết quả này **chỉ chứng minh pipeline** (DRAFT 6.2), không phải độ chính xác ngoài đời thật.
- **Tầng 2 — tín hiệu thật (`app/eta/signals.py`, `eta-signals-v1`)**: đường bộ thật + thời gian lái thông thoáng từ **OSRM** (OpenStreetMap, không khoá) và thời tiết hiện tại từ **Open-Meteo** (không khoá; chọn thay OpenWeatherMap vì không cần đăng ký). ETA điều chỉnh = thời gian OSRM × hệ số xe tải (1,25) × hệ số khung giờ × hệ số thời tiết (mưa/dông/gió); P90 nới theo khung giờ và thời tiết. **Trung thực**: OSRM công khai *không có giao thông thời gian thực* — hệ số khung giờ là **luật**, không phải kẹt xe trực tiếp (muốn dữ liệu kẹt xe thật cần Google Directions/Mapbox có khoá, chưa làm). Tín hiệu chỉ là thông tin **mềm** hiển thị cạnh ETA luật; không đổi hard gate. Tuyến OSRM được **lưu một lần theo chuyến** (`trip_routes`, chỉ khi chuyến chưa chạy) nên hình học bất biến, tiến độ/mốc không nhảy. Lỗi mạng/timeout (2,5 s)/dữ liệu sai → cache âm 60 s, UI báo "dùng ETA luật" và giữ tuyến nội suy mô phỏng. Tắt bằng `PIVOT_SIGNALS_ENABLED=false`; máy chủ riêng: `PIVOT_OSRM_URL` (máy demo công khai chỉ cho fair use).
- Không lưu mô hình dạng blob/pickle; dựng lại xác định khi khởi động (≈ 0,3 giây). Chưa có bảng `eta_observations` (so sánh dự báo với thực tế chuyến thật) — hạ về luật hiện chỉ dựa trên kiểm tra trên dữ liệu mô phỏng.

## Giới hạn đã biết
- Đường đi mặc định là nội suy giữa các địa điểm; chỉ khi lấy được OSRM thì tuyến là đường bộ thật. **Vị trí xe vẫn là GPS mô phỏng** dù chạy dọc đường thật. Tín hiệu ETA chưa được đối chiếu với chuyến thực tế.
- Thông báo "đã đọc" chia sẻ trong cùng tổ chức+vai trò, chưa theo từng người; SMS/email chỉ là nhật ký.
- Dock: một ICD, 2 dock, thời gian bốc dỡ cố định 30′; chưa có lịch nghỉ/bảo trì dock; ràng buộc `btree_gist` chỉ có trong DB đã chạy migration (DB test dựng bằng `create_all` dùng khoá dòng + kiểm tra chồng lấn).
- Ghép lại chỉ cho chuyến **chưa lấy hàng**; sau mốc `DEPARTED_PICKUP` trả `CARGO_ON_BOARD`.
- Playbook/ngưỡng mức độ/SLA là tham số mô phỏng chưa hiệu chỉnh với vận hành thật.
