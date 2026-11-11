# CLAUDE.md — LOGECTION (trước đây PIVOT / VSGA) · AI4Biz Hackathon

> File định hướng cho toàn bộ dự án. **File này được cập nhật liên tục** — mỗi khi có quyết định mới, đổi phạm vi, hoặc hoàn thành một hạng mục, Claude (hoặc người trong team) cập nhật lại các phần "Trạng thái hiện tại", "Quyết định đã chốt" và "Tiến trình" bên dưới. Không cần hỏi lại trước khi ghi nhận tiến trình đã hoàn thành; chỉ hỏi khi có thay đổi phạm vi/kiến trúc ảnh hưởng tới các phần P0.

Căn cứ đánh giá kỹ thuật: `DRAFT.md` (đánh giá công nghệ + kế hoạch Prototype → MVP, cập nhật 09/11/2026). **`DRAFT.md` là nội dung cốt lõi của dự án và BẤT BIẾN — không sửa trong suốt quá trình hoàn thiện sản phẩm; mọi quyết định trong CLAUDE.md phải bám sườn DRAFT.md.** Dự án dự thi: **AI FOR BUSINESS INNOVATION**. Mã nguồn lưu trên GitHub (`khoidesu/PIVOT`) chỉ để backup/versioning, **không tự động push** — chỉ đẩy lên sau mỗi giai đoạn khi được yêu cầu. **Toàn bộ việc build chạy local trên máy của team**, không phụ thuộc CI/CD từ xa ở giai đoạn này.

---

## 0. Trạng thái hiện tại

- **Giai đoạn:** **N3 xong + mở rộng Control Tower (11/11/2026)** — toàn bộ P0 và thêm 4 chức năng theo brief `docs/Đề-Xuất-Mô-Hình-Smart-Logistics-Control-Tower.pdf`: **1 Tracking, 2 ETA, 3 Truck Appointment, 5 Exception Management** (không làm 4, 6, 7, 8 — xem `docs/CONTROL_TOWER.md`). Còn lại: quay video theo `docs/DEMO_SCRIPT.md`, slide (DRAFT mục 12), P1 còn lại (AI nhập liệu với API thật, OR-Tools).
- **Hiện có (11/11/2026, sau Control Tower):**
  - **Control Tower**: màn *Theo dõi* (bản đồ OpenStreetMap, GPS **mô phỏng**, mốc geofence idempotent), *Lịch dock* (Gantt, tự xếp dock, chống trùng lịch, dwell, NO_SHOW, đề xuất dời khi ETA đổi), *Ngoại lệ* (8 loại, mức độ theo luật `sev-v1`, playbook + SLA + leo thang, thông báo mô phỏng, **ghép lại** `POST /v1/proposals/{id}/replan`), chuông thông báo; ETA luật P50/P90 (`assume-v2`) + ETA trực tiếp + ML trên lịch sử mô phỏng có cổng promote/tự hạ về luật; **201 test backend + 15 frontend, 10 kịch bản demo**.
  - Phần lõi bên dưới là trạng thái trước mở rộng (đã tăng test từ 155 lên 201):
  - Backend: 20 bảng + 4 migration · hard gate 8 điều kiện · MatchScore · booking (hold/accept/reject, xác nhận theo từng bên, re-check, `Idempotency-Key`) · events idempotent + outbox + worker (đầu vào xe `VEHICLE_POSITION/AVAILABLE` + chuyến `TRIP_*/ETA_UPDATED`; chỉ nhà vận tải sở hữu xe được báo; payload validate khi nhận) · ngoại lệ do người quyết định · timeline + replay · sổ lợi ích (baseline chốt lúc ghép; verified phải do **bên độc lập**) · **sửa/huỷ yêu cầu** (khoá lạc quan, khoá khi đã giữ/cam kết) · **nhập liệu có dẫn nguồn** (bản nháp, trích đoạn nguồn, rule-based mặc định + adapter LLM chưa chạy thật) · che chi tiết đội xe của tổ chức khác · công cụ demo · **155 test pass**.
  - Frontend: màn hình **đăng nhập (tên + vai trò, mỗi tab một người)** + 6 màn hình nghiệp vụ (menu theo vai trò) + Kịch bản demo ở menu avatar, VI/EN, polling, nhãn MÔ PHỎNG, 15 test frontend. **Giao diện đã gọn chữ ~50–70%** (từ điển 2.645 → 1.364 từ).
- **Triển khai công khai:** phương án chọn mới: **Neon + Hugging Face Spaces** (`docs/DEPLOY_HF_NEON.md`, chưa chạy thật); đã đóng gói (`Dockerfile`, `render.yaml`, `deploy/entrypoint.sh`, `docs/DEPLOY.md`) và kiểm thử container trên máy; **chưa deploy thật** (cần tài khoản Render của người dùng). Mã quản trị `PIVOT_ADMIN_KEY` chặn reset/kịch bản/làm tuổi dữ liệu khi công khai.
- **Chạy local / reset / kiểm thử:** xem `README.md`. Trước mỗi buổi demo: nút "Làm mới dữ liệu demo" hoặc `python -m app.seed`.
- **Báo cáo:** `docs/TEST_REPORT.md` (đối chiếu từng điều kiện nghiệm thu, 6 kịch bản, giới hạn đã biết) · `docs/DEMO_SCRIPT.md` (video ≈ 4 phút).
- **Còn tồn / giới hạn:** AI thật chưa được kiểm chứng (bộ mặc định là luật; LLM adapter chưa chạy với API thật; tập đối chiếu 12 tin do nhóm tự viết) · lợi ích mới một hạng mục, chưa TLC/Bảng A-B-C · ETA rule-based, chưa P50/P90 · ghép từng lô độc lập, chưa phân bổ nhiều xe–hàng (OR-Tools P1) · `request_replan` chưa có luồng huỷ/lập lại chuyến đã cam kết · `external_id_map`/`logistics_units`/`shipment_legs` mới là khung bảng · `proposal.confirmed` mock, token dev, chưa RLS/telemetry/backup/staging. Chi tiết ở `docs/TEST_REPORT.md`.
- **Mục tiêu gần nhất:** hoàn thiện phần trình bày (video, slide) và, nếu còn giờ, P1. **Hạn chót ~13/11/2026.**
- **Ngày bắt đầu:** 10/11/2026.
- **Cập nhật gần nhất:** 11/11/2026 — thêm Control Tower (Tracking, ETA, Truck Appointment, Exception Management); trước đó: đổi tên LOGECTION, gọn giao diện.

> Cập nhật mục này mỗi khi kết thúc một ngày làm việc / một hạng mục P0-P1 trong Backlog (mục 9).

---

## 1. Dự án là gì

PIVOT/VSGA là mô hình điều phối logistics (ghép xe sắp trống với hàng sẵn sàng, qua kiểm tra khả thi → giữ slot → xác nhận → theo dõi → ghi nhận lợi ích), chuyển từ thiết kế/giả định sang một sản phẩm **chạy thử được, đo được giá trị, mở rộng có kiểm soát**.

Nguyên tắc cốt lõi cần giữ xuyên suốt, không đổi vì lý do "cho đẹp slide":

- **Kiến trúc điều phối dựa trên sự kiện** (event-driven), không phải batch job đơn thuần.
- **Hard gate trước khi chấm điểm** — một ứng viên không đạt điều kiện bắt buộc thì bị loại thẳng, không đưa vào chấm điểm MatchScore.
- **Quyền xác nhận thuộc về chủ thể vận hành** (carrier nhận việc, shipper duyệt lô, node duyệt slot) — hệ thống đề xuất, con người/đối tác xác nhận. AI/LLM không được tự tạo lý do sau quyết định hay tự xác nhận booking.
- Mỗi khuyến nghị phải có: dữ liệu nguồn, lý do chọn/loại, phiên bản rule/model, phép tính lợi ích **kiểm tra lại được** (reproducible).

Luồng lõi (không được cắt bớt, kể cả ở bản demo rút gọn):
xe sắp trống → hàng sẵn sàng → kiểm tra khả thi (hard gate)
→ giữ slot (hold có hạn) → xác nhận → theo dõi → ghi nhận lợi ích


---

## 2. Phạm vi đã chốt cho bản demo

Đây là quyết định đang áp dụng; nếu có thay đổi, sửa trực tiếp mục này và ghi lý do.

- **Theo sát kế hoạch Prototype 5 ngày trong DRAFT.md (mục 3.1 + mục 8)**, không phải MVP đầy đủ 10 tuần.
- 1 hành lang khu công nghiệp–ICD, hàng khô, 10 xe / 20 lô / 20 slot, 3 tổ chức, 4 vai trò: shipper, carrier, node operator, điều phối viên.
- 6 màn hình bắt buộc: (1) nhập yêu cầu, (2) danh sách xe/hàng, (3) khuyến nghị + lý do, (4) xác nhận/slot, (5) timeline + ngoại lệ, (6) bảng lợi ích theo chuyến. Bản đồ chỉ là bổ trợ, không phải điều kiện demo thành công.
- Mọi dữ liệu seed/slot tự tạo trong prototype **là dữ liệu mô phỏng và phải được gắn nhãn rõ** trên UI (mock/live) — không hiển thị như đặt chỗ thật khi chưa có API/người xác nhận thật.
- Nếu thiếu thời gian: **bỏ AI nhập liệu (mục 6.1) trước tiên**, giữ nguyên xử lý xác nhận, dữ liệu lỗi, truy vết (audit). Không được thay phần lõi (hard gate, state machine booking) bằng nút bấm giả lập kết quả cố định.
- **Mở rộng (11/11/2026, người dùng quyết)**: thêm 4 chức năng Control Tower (Tracking, ETA, Truck Appointment, Exception Management) trên luồng lõi; **không** làm cold chain, returns, emissions, KPI dashboard tổng. Màn hình tăng từ 6 lên 9 (+ Theo dõi, Lịch dock, Ngoại lệ). Mọi dữ liệu GPS/dock/lịch sử ETA/SMS-email vẫn là mô phỏng và gắn nhãn.
- Hoãn đến khi có dữ liệu/bài toán chứng minh được: LSTM, GNN, blockchain/smart contract, digital twin, cold chain, tối ưu đa hành lang.

---

## 3. Tech stack đã chốt (theo Bảng 2, DRAFT.md)

Đây là stack mặc định để code theo. **Được phép đề xuất đổi** nếu trong quá trình build thấy không phù hợp hoặc chưa tối ưu — nhưng phải nêu lý do cụ thể và cập nhật lại bảng này (không âm thầm đổi).

| Lớp | Chọn | Ghi chú triển khai |
|---|---|---|
| Giao diện | React + TypeScript + Vite (+ Leaflet / OpenStreetMap cho bản đồ) | 1 web responsive; luôn hiển thị nguồn dữ liệu + tuổi dữ liệu (mock/live, data age) trên UI |
| Backend | FastAPI + Pydantic; SQLAlchemy + Alembic | API có schema/type rõ; module hoá: intake, events, matching, booking, benefits |
| Dữ liệu | PostgreSQL (+ PostGIS nếu cần lọc không gian) | DB giao dịch chính; không thêm PostGIS nếu chưa cần |
| Xử lý nền | Worker đọc jobs/outbox trong PostgreSQL | Lease/lock, retry có giới hạn, bảng lỗi + replay. Chưa cần Kafka |
| Đăng nhập | OIDC provider có sẵn | Không tự xây mật khẩu; backend check token + tổ chức + quyền trên tài nguyên |
| AI / tối ưu | scikit-learn (ETA ML mô phỏng — đã dùng); OR-Tools; adapter LLM (nếu dùng) | ETA và parsing tách module riêng; solver có timeout; ghi version model |
| Hạ tầng | Object storage; container; CI/CD; telemetry | Tệp riêng tư; tách staging/production; có backup + thực tập restore |
| Cập nhật UI | Polling trước; SSE nếu cần | Tránh WebSocket khi chưa cần giao tiếp hai chiều |
| Ngôn ngữ UI | i18n song ngữ Việt/Anh (thêm 10/11/2026) | Có nút chuyển ngôn ngữ; `reason_code` và mã trạng thái giữ tiếng Anh ở cả hai ngôn ngữ |

> Quy ước: mọi thay đổi stack phải trả lời được "đổi để giải quyết vấn đề gì, đánh đổi gì" — không đổi theo trend.

---

## 4. Kế hoạch 5 ngày (Bảng 3, DRAFT.md) — checklist tiến trình

### Lịch nén 3 ngày (áp dụng từ 10/11/2026, thay cho lịch 5 ngày bên dưới)

Giữ nguyên toàn bộ "điều kiện qua" của DRAFT; chỉ gộp ngày và cắt phần P1.

| Ngày | Gộp từ | Nội dung |
|---|---|---|
| N1 (10/11) | Ngày 1 + nửa đầu Ngày 2 | Schema/seed/phân quyền A/B + hard gate + reason_code |
| N2 (11–12/11) | nửa sau Ngày 2 + Ngày 3 + nửa đầu Ngày 4 | MatchScore + UI giải thích, booking hold/accept/reject + race test, idempotent event |
| N3 (12–13/11) | nửa sau Ngày 4 + Ngày 5 | Timeline/ngoại lệ, benefit ledger, 6 kịch bản demo, seed/reset, video |

**Không cắt hạng mục nào của prototype** (người dùng đảm bảo đủ thời gian). Làm theo thứ tự DRAFT: lõi P0 trước (hard gate, state machine booking, idempotency, phân quyền A/B, nhãn mô phỏng, timeline, ledger), rồi P1 (AI nhập liệu, ETA baseline, OR-Tools) nếu còn giờ — P1 không bị loại, chỉ xếp sau P0. Đơn giản hoá cho demo local: OIDC dùng token dev + bộ chọn vai trò trên UI; demo chạy local, không CI/staging từ xa.

Cập nhật checkbox khi hoàn thành. Mỗi ngày có "điều kiện qua" — không tick xong ngày nếu điều kiện qua chưa pass.

- [x] **Ngày 1 — Nền tảng:** chốt schema, vai trò, seed; dựng UI/API/DB + CI. *(10/11/2026: schema/seed/API/phân quyền xong, test A/B pass; UI từ N2, CI/staging từ xa không làm — demo chạy local)*
  - Deliverable: 20 lô, 10 xe, 20 slot; 3 tài khoản tổ chức.
  - Điều kiện qua: tạo/đọc lô OK; tổ chức A **không** đọc được lô riêng của B.
- [x] **Ngày 2 — Hard gate & score:** viết hard gate, MatchScore, phép tính chi phí; giao diện giải thích lý do. *(10/11/2026: gate 8 điều kiện, MatchScore, màn hình khuyến nghị có lý do template; test pass)*
  - Deliverable: candidate list + reason_code; thông số có version.
  - Điều kiện qua: loại đúng xe thiếu tải / sai loại hàng / trễ giờ; input thiếu bị chặn (không âm thầm PASS).
- [x] **Ngày 3 — Booking:** hold/accept/reject, hết hạn, slot có capacity. *(10/11/2026: state machine đến `completed` qua sự kiện, race test + idempotency + worker restart pass)*
  - Deliverable: 1 luồng xác nhận chạy đến `completed`.
  - Điều kiện qua: 2 request nhận đồng thời → chỉ 1 thành công; gửi lại event không bị nhân đôi tác động.
- [x] **Ngày 4 — Timeline & lợi ích:** timeline, ngoại lệ, replay, benefit ledger; AI nháp nếu lõi đã qua. *(10/11/2026: màn timeline + ngoại lệ có xử lý, replay tái lập, sổ lợi ích estimated/measured/verified; **AI nháp (P1) chưa làm** — đúng thứ tự DRAFT: chỉ làm khi lõi đã qua)*
  - Deliverable: ETA đổi → tạo ngoại lệ; so sánh baseline–actual; bản nháp AI có dẫn nguồn (nếu làm).
  - Điều kiện qua: không tự sửa chuyến đã cam kết; parsing thiếu trường không tạo lô hiệu lực.
- [x] **Ngày 5 — Đóng gói demo:** test lỗi, seed/reset, đóng gói. *(10/11/2026: 6 kịch bản lặp lại được, reset/retime, README + `docs/TEST_REPORT.md` + `docs/DEMO_SCRIPT.md`; **chưa có** link staging (demo chạy local) và **chưa quay video** — mới có kịch bản)*
  - Deliverable: link staging, hướng dẫn chạy, test report, video demo 3–5 phút.
  - Điều kiện qua: 6 kịch bản demo (mục 6) lặp lại được; mọi số liệu mô phỏng được gắn nhãn rõ.

**6 kịch bản demo bắt buộc** (dùng để test + quay video): ghép thành công · xe không tương thích bị loại · dữ liệu quá hạn (stale) · hai người giữ cùng một tài nguyên (race condition) · ETA đổi làm phương án cũ không còn phù hợp (tạo ngoại lệ) · sự kiện gửi trùng / worker restart (không nhân đôi tác động).

---

## 5. Mô hình dữ liệu tối thiểu

**Bảng cần tạo:** `organizations, users, memberships, shipments, shipment_legs, logistics_units, shipment_participants, vehicles, availability_windows, locations, slots, events, external_id_map, proposals, reservations, decisions, exceptions, benefit_ledger, assumption_sets, outbox_jobs`.

**Event tối thiểu:** `event_id, schema_version, tenant_id, entity_type, entity_id, event_type, occurred_at, received_at, source_system, source_event_id, payload, quality_status, correlation_id`.

Quy tắc bắt buộc:
- Lưu UTC; UI hiển thị theo múi giờ vận hành. Giữ riêng `occurred_at` và `received_at` để đo độ trễ dữ liệu.
- Unique trên `source_system + source_event_id`; endpoint nhận hỗ trợ `Idempotency-Key`. Gửi lại 1 event không được tạo tác động nghiệp vụ lần 2.
- Sự kiện gốc giữ nguyên; sự kiện sửa phải tham chiếu bản trước. Tin đến muộn không được tự kéo trạng thái lùi (vd từ `completed` về `in_transit`).
- Đổi trạng thái + ghi outbox trong **cùng transaction**. Không hứa exactly-once end-to-end — worker retry, consumer phải idempotent.
- Mỗi đối tác có `external_id` mapping riêng; khi gộp/tách hàng giữ quan hệ `shipment–leg–logistics_unit`, không gán 1 mã cho mọi đối tượng.
- Dùng `tenant_id` để cô lập dữ liệu; RLS là lớp bảo vệ **bổ sung**, không thay cho kiểm tra quyền ở tầng ứng dụng (đặc biệt field giá, khách hàng, tệp).

---

## 6. Chuỗi xử lý quyết định (bắt buộc giữ nguyên thứ tự)
Kiểm tra quyền & tuổi dữ liệu → lọc ứng viên gần phù hợp → hard gate
→ ước tính lợi ích → xếp hạng → giữ nguồn lực (hold) → xác nhận
→ kiểm tra lại (re-check) → thực thi

- Hard gate trả về `PASS | FAIL | UNKNOWN` + `reason_code`. Trường bắt buộc mà `UNKNOWN` → chuyển sang "cần bổ sung dữ liệu", **không được âm thầm coi là PASS**.
- Ví dụ reason_code: `CARGO_INCOMPATIBLE, CAPACITY_EXCEEDED, PICKUP_WINDOW_MISSED, CUTOFF_RISK, VEHICLE_UNAVAILABLE, SLOT_FULL, DATA_STALE, ID_UNRESOLVED`.
- Khi không có phương án đạt → trả "không có phương án khả thi" kèm lý do. **Không ép ghép.**
- MatchScore: tiêu chí đưa về thang 0–1, trọng số cộng = 1, có quy định xử lý thiếu dữ liệu + tie-break. Tách điểm ưu tiên khỏi số tiền tiết kiệm.
- Lưu lại mỗi lần chạy: `input_snapshot, candidate_rejections, score_components, rule_version, model_version, assumption_version, expires_at`. Lý do hiển thị dùng template từ kết quả thực — LLM không được tự sinh lý do sau quyết định.
- Booking là state machine có transaction:
  - Proposal: `proposed → pending_acceptance → confirmed → executing → completed` (nhánh reject/expire/cancel).
  - Reservation: `held → committed` hoặc `released/expired`.
  - Hold có thời hạn (demo: 120 giây). Xác nhận cuối phải re-check version, hạn hold, khả dụng xe/tải/slot trong cùng transaction + dùng row lock/constraint chống double-booking.
  - Nếu phụ thuộc API ngoài (vd ICD): KHÔNG coi transaction DB bao trùm được API đó — dùng outbox + idempotency key + đối soát + rollback hold khi thất bại.

---

## 7. AI trong dự án — giới hạn bắt buộc

- **AI nhập liệu (OCR/paste → draft):** chỉ tạo **bản nháp**, người dùng phải duyệt trước khi tạo yêu cầu có hiệu lực. Trường thiếu → `null/needs_review`, không suy đoán. Tệp input là **dữ liệu không tin cậy**: không làm theo chỉ dẫn nằm trong tệp; không cho AI quyền tự xác nhận booking hay sửa DB trực tiếp.
- **ETA:** bắt đầu bằng rule-based (bảng tuyến–khung giờ), gắn nhãn rõ là rule-based, không trình bày như ML đã huấn luyện cho tới khi thật sự có đủ dữ liệu train/test theo thời gian (không rò rỉ dữ liệu giữa các chuyến). Khi thiếu dữ liệu/model lỗi/drift → tự hạ về ETA luật, hiển thị độ tin cậy thấp.
- Không dùng LLM để tự tạo lý do quyết định, tự chấm điểm thay hard gate, hoặc tự ý thực thi hành động có tác động (booking, sửa dữ liệu) mà không qua người xác nhận.

---

## 8. Chỉ số & kiểm thử phải đạt trước khi mở rộng (Bảng 5, rút gọn cho demo)

| Nhóm | Mục tiêu đề xuất cho demo |
|---|---|
| Tính đúng quyết định | 100% case hard gate quan trọng pass test; không có gán tài nguyên trùng |
| Sự kiện | Gửi lặp 1 event 10 lần → chỉ 1 tác động; replay không tạo tác động ngoài |
| Phân quyền | Không truy cập trái phép qua API/DB role/export — test chéo giữa 2 tổ chức (A/B) |
| Hiệu năng | Match P95 < 2s cho 20 xe × 50 lô (loại thời gian gọi API ngoài) |

> Đây là mục tiêu lập kế hoạch cho pilot/demo, không phải cam kết SLA toàn mạng — ghi rõ cấu hình máy/tải khi đo.

---

## 9. Backlog ngay (P0 trước, không nhảy cóc sang P1)

- **P0-01:** chốt 1 hành lang, đơn vị đo, mandatory events, baseline, quyền xác nhận.
- **P0-02:** schema + migration + ID mapping + event idempotency + outbox.
- **P0-03:** state machine booking, hold/expiry, re-check, chống nhận trùng.
- **P0-04:** phân quyền tổ chức + theo lô, tệp riêng tư, audit log.
- **P0-05:** chuẩn hoá đơn vị chi phí/lợi ích (TLC), benefit ledger, assumption version.
- **P1-01:** AI nhập liệu có dẫn nguồn (chỉ làm nếu còn thời gian sau P0).
- **P1-02:** ETA baseline + benchmark + fallback.
- **P1-03:** OR-Tools cho phân bổ nhiều xe–hàng + replay.

Thứ tự đầu tư: **dữ liệu & giao dịch đúng → vòng điều phối có người dùng thật → lợi ích verified → AI/tối ưu tăng thêm.** Mỗi lần tăng độ phức tạp phải trả lời được: đổi gì lấy kết quả gì.

---

## 10. Quyết định đã chốt (changelog)

Ghi mỗi quyết định quan trọng ở đây theo thời gian, mới nhất trên đầu. Không xoá lịch sử quyết định cũ — nếu đổi thì thêm dòng mới ghi rõ "thay thế quyết định ngày ...".

- **11/11/2026 (deploy Neon + Hugging Face)** — Người dùng hỏi lưu DB bằng Firebase; **không đổi sang Firestore** (cả hệ thống dựa trên khoá dòng, ràng buộc duy nhất, giao dịch nhiều bảng, outbox `SKIP LOCKED` của PostgreSQL — viết lại là nhiều ngày và mất bảo đảm đua/idempotency). Chọn **Neon (Postgres managed, free) + Hugging Face Spaces (Docker)** để có link 24/7 và dữ liệu bền: thêm cờ `PIVOT_ALLOW_FRAMING` (bỏ `X-Frame-Options` để chạy trong khung HF), `pool_recycle=300`, `deploy/hf/` (README Space + `push_space.sh`, cố định cổng 7860), hướng dẫn `docs/DEPLOY_HF_NEON.md`. Đã chạy thử image dựng từ gói Space ở cổng 7860, 10/10 kịch bản; **chưa chạy thật trên HF/Neon** (cần tài khoản người dùng). Rủi ro: worker truy vấn mỗi giây nên Neon không tự ngủ → tốn giờ tính toán free; Space công khai.
- **11/11/2026 (Control Tower)** — Người dùng nhận xét web chỉ là lớp ghép nối (đã có nhiều mô hình tương tự) nên chọn thêm chức năng **1 Tracking, 2 ETA, 3 Truck Appointment, 5 Exception Management** từ brief Control Tower (thứ tự làm 1 → 5 → 3 → 2; nếu thiếu giờ cắt ML của ETA trước). Quyết định thiết kế: (1) **GPS mô phỏng + bản đồ OSM thật** (Leaflet; toạ độ/đường đi là nội suy mô phỏng, luôn gắn nhãn); vị trí đi qua `POST /v1/events` (nhà vận tải sở hữu xe) → outbox → worker, mốc geofence suy ra từ vị trí và là sự kiện hệ thống `MILESTONE_REACHED` (unique theo chuyến+mốc; gửi từ ngoài → 422); (2) **hard gate giữ nguyên P50** — P90 chỉ cho cảnh báo mềm (`cutoff_risk_p90`, `DELAY_RISK`), khung giờ chỉ nới P90 nên quyết định ghép không đổi theo giờ chạy test; bộ giả định nâng lên **`assume-v2`** (thêm khối `eta`), thay thế `assume-v1`; (3) **ML ETA** (numpy + scikit-learn, **thay đổi stack có lý do**: cần phân vị P50/P90 và benchmark so với luật; đánh đổi: image lớn hơn, RAM) huấn luyện trên lịch sử **do nhóm sinh** (seed cố định), chia theo thời gian [fit | hiệu chỉnh P90 | test], chỉ promote khi MAE giảm ≥ 15% và độ phủ P90 ∈ [0,85; 0,97], lỗi/trôi → tự hạ về luật; kết quả chỉ chứng minh pipeline (DRAFT 6.2); bỏ bảng `eta_observations` đã định trong kế hoạch (chưa có chuyến thật để đối chiếu); (4) **ngoại lệ**: mức độ/playbook/SLA là luật có version (`sev-v1`/`pb-v1`), mỗi bước chỉ bên chịu trách nhiệm hoàn tất (điều phối viên không làm thay), quá SLA → leo thang tới điều phối viên; SMS/email là **nhật ký giả lập** không gọi nhà cung cấp, không PII; (5) **ghép lại** đóng ngõ cụt `request_replan`: người dùng chủ động gọi, chỉ khi chưa lấy hàng (`CARGO_ON_BOARD` sau `DEPARTED_PICKUP`), trả xe/slot/dock, lô về `open`, xe hỏng chuyển `offline`; hệ thống **không tự đổi chuyến**; (6) **lịch dock**: khoá dock `FOR UPDATE` + kiểm tra chồng lấn trong cùng transaction (lớp chính) + ràng buộc loại trừ `btree_gist` trong migration (bổ sung, có phương án khi DB không cho bật); ETA đổi chỉ **đề xuất** khung mới, ICD chấp nhận mới áp dụng; (7) kịch bản demo tăng 6 → **10**, thêm tham số `speedup` cho bộ giả lập để chạy kịch bản trong vài giây. Lỗi tìm được: làm tròn khung dock xuống thay vì lên. Không làm: cold chain, returns, emissions, KPI dashboard tổng. Chi tiết: `docs/CONTROL_TOWER.md`.
- **10/11/2026 (deploy công khai)** — Người dùng chọn **Render** + **mở cho mọi người nhưng bảo vệ nút phá dữ liệu**. Quyết định: (1) một image Docker phục vụ cả giao diện (API cùng origin, không CORS) và API; khởi động tự `alembic upgrade head` rồi seed **chỉ khi DB trống** (không ghi đè dữ liệu người dùng sau mỗi lần deploy); (2) giữ đăng nhập token dev (demo, dữ liệu mô phỏng) nhưng thao tác phá dữ liệu cần thêm header `X-Admin-Key` (`PIVOT_ADMIN_KEY`, so sánh hằng thời gian) **và** vai điều phối viên — mã chỉ lưu trong sessionStorage của tab; (3) `postgres://` của nhà cung cấp tự đổi sang `postgresql+psycopg://`; (4) thêm header an toàn cơ bản; (5) **không** đặt khoá LLM trên bản công khai (endpoint nhập liệu mở → nguy cơ tốn tiền); (6) rủi ro chấp nhận: không OIDC, không rate limit, `/docs` mở, dữ liệu dùng chung ai cũng sửa được.
- **11/11/2026 (đổi tên LOGECTION + gọn giao diện)** — Dự án đổi tên **LOGECTION**: chỉ đổi phần nhìn thấy (giao diện, tiêu đề tab, favicon chữ L, tiêu đề API, README/docs/CLAUDE.md); **giữ** `PIVOT_*`, tên DB, Docker/Render, repo `khoidesu/PIVOT`, khoá `pivot.*` trong storage; `DRAFT.md` bất biến nên vẫn gọi PIVOT/VSGA. Gọn giao diện vì người dùng thấy quá nhiều chữ/phần dư: quy tắc chữ (nhãn ≤ 4 từ, gợi ý ≤ 1 câu, giải thích vào tooltip `Hint`, chi tiết kỹ thuật vào `More`/"Chi tiết", **một** chip MÔ PHỎNG ở thanh đầu thay vì lặp trên từng dòng/thẻ); thanh đầu gom vào **menu avatar** (ngôn ngữ, làm mới dữ liệu, kịch bản demo, đăng xuất), bỏ đồng hồ máy chủ; **menu theo vai trò** (`navFor`), ICD chỉ thấy Slot · Xác nhận · Hành trình, route không được phép tự về mục mặc định; tab Demo chuyển vào menu avatar của Điều phối viên. Không đổi logic nghiệp vụ; điều kiện/điểm/phiên bản/tái lập vẫn truy cập được ở mục *Chi tiết*. Đo thật trước/sau trong `docs/TEST_REPORT.md`.
- **11/11/2026 (đăng nhập đơn giản)** — Thay bộ chọn vai trò bằng **đăng nhập tên + vai trò** (không mật khẩu, chỉ cho dữ liệu mô phỏng); phiên ở `sessionStorage` nên **mỗi tab một người**, muốn thử nhiều bên thì mở nhiều tab. Quyết định thiết kế: (1) danh tính = (tên, vai trò); tên mới = tổ chức riêng + dữ liệu mẫu theo vai trò (chủ hàng 4 lô, nhà vận tải 4 xe, ICD 8 slot) để test được "bên A, bên B khác nhau"; (2) năm cặp tên+vai trò của nhóm (Nguyên/Phước, Minh, Khôi, Phú) nối vào tài khoản mẫu A/B/C để 6 kịch bản demo, test và báo cáo giữ nguyên; (3) token vẫn là `dev:<khoá>` nên `current_actor` và mọi kiểm tra quyền không đổi; (4) **reset toàn bộ giữ danh tính** người đã đăng nhập và cấp lại dữ liệu mẫu (tab đang mở không bị văng); (5) **retime bỏ qua dữ liệu của người tự đăng ký** (tạo sau mốc anchor nên dịch sẽ sai) — họ làm tươi dữ liệu bằng luồng thật (nhà vận tải *Cập nhật vị trí cả đội*, chủ hàng sửa lô); (6) bản công khai có trần 500 người đăng ký + mã quản trị cho thao tác phá dữ liệu. (7) **kịch bản demo chạy trên dữ liệu seed thuần** (reset `provision=false`) rồi cấp lại dữ liệu mẫu cho người đăng ký — vì xe/slot của họ có thể bị ghép trúng và làm kịch bản không xác định (phát hiện khi chạy trên server thật: 3/6 lỗi dù test xanh); chạy kịch bản xoá dữ liệu nghiệp vụ của mọi người kể cả lô họ tự tạo. Giới hạn: không mật khẩu, tên khác dấu trùng tài khoản, nhân đôi tab sao chép phiên.
- **10/11/2026 (review lần 2 + tính năng)** — (1) **Sự kiện đúng chủ thể**: số đo/vị trí/ETA chỉ do nhà vận tải sở hữu xe báo, payload validate khi nhận (km 0–500, delay 1–1440 phút, không nhận sự kiện từ tương lai >5 phút); (2) **xác minh độc lập**: bên báo số đo không tự xác minh; lô do forwarder tự chở dừng ở `measured` (thay thế quy tắc cũ "chủ lô hoặc nhà vận tải đều xác minh được"); (3) **che dữ liệu**: xe bị loại của tổ chức khác chỉ hiện biển số đã che + mã lý do + dữ kiện của lô người xem (bản đầy đủ vẫn lưu để audit); (4) GET không ghi DB — worker dọn hold quá hạn mỗi vòng, trạng thái `expired` được suy ra khi hiển thị (thay thế hết hạn lười trong GET); danh sách đề xuất dựng theo lô (79 → 8 truy vấn); (5) **event-driven đầu vào cho xe**: `VEHICLE_POSITION`/`VEHICLE_AVAILABLE` idempotent, tin cũ → `late`; (6) **sửa/huỷ yêu cầu**: `PATCH` với khoá lạc quan, `DELETE` = huỷ mềm (không xoá cứng vì sự kiện/đề xuất/sổ lợi ích tham chiếu lô — giữ audit); chỉ chủ lô; khoá khi đã giữ/cam kết; sửa làm mới dữ liệu và vô hiệu đề xuất `proposed` cũ; (7) **nhập liệu có dẫn nguồn (P1-01, làm sớm theo yêu cầu người dùng)**: chỉ bản nháp; mặc định bộ phân tích theo luật gắn nhãn "không phải AI"; adapter LLM tuỳ chọn qua biến môi trường, chưa chạy với API thật; kiểm tra bằng luật, trích đoạn nguồn bắt buộc, không lưu văn bản gốc.
- **10/11/2026 (N3)** — Quyết định thiết kế N3: (1) baseline lợi ích chốt trong snapshot lúc ghép, không tính lại sau (DRAFT 11.1); chỉ khoản `measured` mới xác minh được, và chỉ chủ lô/nhà vận tải của chuyến xác minh (điều phối viên, node thì không); (2) ngoại lệ do chủ lô/nhà vận tải quyết định (`accept_delay` | `request_replan`), hệ thống không tự đổi xe; (3) `replay` tính lại điểm từ thành phần + trọng số đã lưu để chứng minh tái lập; (4) 6 kịch bản demo là mã dùng chung cho endpoint, pytest và CLI, chạy qua API thật bằng token của từng thành viên, mỗi kịch bản tự reset; (5) **reset dùng `DELETE` theo thứ tự khoá ngoại thay cho `TRUNCATE`** (TRUNCATE bế tắc với worker/request song song — phát hiện khi chạy tab Demo, có test hồi quy); (6) thêm tab thứ 7 "Kịch bản demo" (ngoài 6 màn hình bắt buộc của DRAFT, chỉ vai Điều phối viên chạy được); (7) hiệu năng ghép đo thật: p95 = 30 ms cho 20 xe × 50 lô.
- **10/11/2026 (chỉnh UI trước N3)** — Bỏ dải banner "DỮ LIỆU MÔ PHỎNG · MOCK…" trên cùng (vẫn giữ huy hiệu ● MÔ PHỎNG ở thanh đầu và nhãn trên từng lô/slot/đề xuất để không để số liệu giả trông như thật). Bộ chọn vai trò gồm 5 thành viên thật của nhóm: Nguyên (Chủ hàng A), Phước (Chủ hàng A, nhân viên thứ 2 — test chia sẻ trong cùng tổ chức), Minh (Vận tải B), Khôi (ICD Cảng C), Phú (Điều phối viên). Bỏ khối giải thích "Vì sao cần đủ trường?" ở màn nhập yêu cầu.
- **10/11/2026 (N2)** — Quyết định thiết kế N2: (1) xác nhận theo từng bên (shipper duyệt lô / carrier nhận việc / node duyệt slot), điều phối viên được giữ slot nhưng không xác nhận thay; forwarder sở hữu cả lô và xe thì một lần xác nhận phủ hai bên; (2) khi một đề xuất `confirmed`, các đề xuất mở còn lại của lô bị `cancelled` (một lô – một cam kết); (3) hold hết hạn xử lý lười trong transaction (partial unique index không tham chiếu `now()` được) và `retime` expire đề xuất/hold đang mở; (4) trạng thái thực hiện chỉ đổi bằng sự kiện (`TRIP_STARTED/TRIP_COMPLETED/ETA_UPDATED`) qua outbox worker — tin muộn không kéo lùi trạng thái, ETA đổi chỉ tạo ngoại lệ với chuyến đã cam kết; (5) ETA là rule-based, quãng đường là đường chim bay × 1.3 (xấp xỉ, UI ghi nhãn); (6) giả định đang hiệu lực chọn bằng cờ `is_active`, không suy từ ngày tạo; (7) frontend không dùng router/UI lib: hash routing + CSS thuần, i18n tự viết (mã lý do giữ tiếng Anh).
- **10/11/2026 (review N1)** — Sau code review backend: (1) DB chỉ bind 127.0.0.1; (2) `ShipmentCreate` bắt buộc múi giờ + `ready_at < pickup_deadline < cutoff_at`, location không tồn tại → 422 (trước đó 500); (3) mã lô unique theo `(tenant_id, code)` thay vì toàn cục để không lộ lô của tenant khác — thay thế thiết kế ban đầu; (4) thêm partial unique index chống đặt trùng xe/lô trên `reservations`, CHECK status cho shipments/proposals/reservations, `decisions.idempotency_key` unique theo tổ chức; (5) seed có chốt chặn `data_mode=mock`, lệnh `--retime` và `POST /v1/demo/retime` để demo không bị DATA_STALE theo thời gian. Còn tồn: gate_slot chưa kiểm slot đúng ICD đích, tuổi dữ liệu của lô, auth nhiều membership, N+1 nhẹ ở danh sách lô.
- **10/11/2026 (style UI)** — Chốt style "Control Tower tối giản": nền sáng, nhấn teal, bo góc 12px, thẻ rõ ràng, badge PASS/FAIL/UNKNOWN; thanh đầu có bộ chọn vai trò, VI|EN, badge MOCK/LIVE + tuổi dữ liệu. Frontend bắt đầu từ N2, backend lõi xong trước.
- **10/11/2026 (phạm vi)** — Người dùng xác nhận không cắt hạng mục nào trong lịch nén; P1 vẫn xếp sau P0. Chọn phiên bản công nghệ (Python 3.13, Postgres cổng 5433…) do Claude tự quyết. Thay thế dòng "cắt P1" ngay bên dưới.
- **10/11/2026 (hạn chót)** — Hạn nộp còn 3 ngày thay vì 5 → nén lịch còn 3 ngày (mục 4). OIDC dùng token dev, bỏ CI/staging từ xa. Giữ nguyên P0 và điều kiện qua của DRAFT. (Phần "cắt P1" của dòng này đã bị thay thế bởi dòng phạm vi phía trên.)
- **10/11/2026 (bổ sung)** — Chốt loại demo = prototype chạy được (6 màn hình), không phải landing page. Backend = stack thật FastAPI + PostgreSQL local (Docker), không dùng SQLite/mock. UI song ngữ Việt/Anh (thêm vào Bảng stack). Thay thế các tham chiếu `AI4Biz.md` bằng `DRAFT.md` (tên file thực tế); `DRAFT.md` được khai báo bất biến. Repo GitHub là `khoidesu/PIVOT`, chỉ push khi được yêu cầu.
- **10/11/2026** — Khởi tạo CLAUDE.md. Chốt phạm vi = Prototype 5 ngày theo AI4Biz.md mục 3.1/8 (chưa cắt giảm thêm). Chốt stack = Bảng 2 AI4Biz.md, được phép đề xuất đổi khi có lý do kỹ thuật cụ thể. Build local, GitHub chỉ dùng lưu trữ mã nguồn.

---

## 11. Quy tắc làm việc cho Claude khi code trong repo này

- Không đổi nguyên tắc cốt lõi ở mục 1 (event-driven, hard gate trước score, quyền xác nhận thuộc đối tác) khi chưa hỏi người dùng.
- Mỗi tính năng P0 phải đi kèm cách test ở mục 8/Bảng 3 tương ứng — không coi là "xong" nếu chưa pass điều kiện qua.
- Dữ liệu demo/mô phỏng phải gắn nhãn rõ ràng trên UI; không để số liệu giả trông như số liệu thật.
- Khi hoàn thành 1 ngày trong checklist (mục 4), cập nhật luôn mục 0 (Trạng thái hiện tại) và tick checkbox tương ứng.
- Khi đề xuất đổi công nghệ so với mục 3, phải ghi lý do vào mục 10 (changelog) trước khi áp dụng, không đổi âm thầm.
- Tài liệu gốc đầy đủ (chi tiết API, bảng biểu, công thức kinh tế/sustainability, nguồn tham khảo kỹ thuật) nằm trong `DRAFT.md` — tham chiếu lại khi cần chi tiết, không cần chép lại toàn bộ vào đây.