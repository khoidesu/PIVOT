# PIVOT / VSGA \- Đánh giá công nghệ và kế hoạch Prototype → MVP

**Mục tiêu:** chuyển mô hình điều phối logistics trong 5changlinhngulam thành một sản phẩm có thể chạy thử, đo được giá trị và mở rộng có kiểm soát. Ngày cập nhật: 09/11/2026.

**Phạm vi đánh giá:** thiết kế và giả định trong 5changlinhngulam, chưa có mã nguồn, dữ liệu chuyến thực tế hoặc kết quả benchmark để kiểm tra chất lượng triển khai. Các ngưỡng nghiệm thu, thời lượng và phạm vi dưới đây là đề xuất lập kế hoạch, cần chốt với đối tác pilot.

# **1\. Quyết định công nghệ nên chốt ngay**

Giữ kiến trúc điều phối dựa trên sự kiện, hard gate trước chấm điểm và quyền xác nhận của chủ thể vận hành. Thu hẹp bản đầu vào một luồng: xe sắp trống → hàng sẵn sàng → kiểm tra khả thi → giữ slot → xác nhận → theo dõi → ghi nhận lợi ích.

Điểm nổi bật nên chọn: mỗi khuyến nghị đi kèm dữ liệu nguồn, lý do chọn/loại, phiên bản quy tắc và phép tính lợi ích có thể kiểm tra. Lợi thế này gắn trực tiếp với niềm tin doanh nghiệp và khả năng chứng minh hiệu quả kinh tế.

* P0 \- bắt buộc: mô hình dữ liệu, phân quyền doanh nghiệp, quy trình xác nhận, chống đặt trùng, dữ liệu quá hạn, kiểm thử và sổ ghi nhận lợi ích.  
* P1 \- sau luồng lõi: AI nhập liệu có dẫn nguồn; ETA có benchmark; phân bổ nhiều xe–hàng; giám sát chất lượng dữ liệu.  
* P2 \- theo gate mở rộng: cold chain, sea-air, tối ưu đa hành lang, mô phỏng.  
* Hoãn LSTM, GNN, blockchain/smart contract và digital twin cho đến khi có bài toán, dữ liệu và lợi ích vượt chi phí được chứng minh. Không đổi mô hình chỉ vì đến năm 2028 hoặc 2030\.

# **2\. Đánh giá mô hình hiện tại và việc cần sửa**

**Bảng 1\. Khoảng trống cần ưu tiên**

| Hạng mục | Nhận định | Sửa cụ thể | Mức |
| :---- | :---- | :---- | :---- |
| Kiến trúc L1-L5 | Luồng xử lý hợp lý; thiếu ranh giới triển khai. | Một backend chia module; một worker; một PostgreSQL. Có version API và schema. | P0 |
| Dữ liệu chung | EPCIS/SSCC là hướng phù hợp; chưa đủ định danh nội bộ. | Bổ sung shipment, leg, unit, vehicle, event; bảng ánh xạ ID từng đối tác. | P0 |
| Hard gate | Giữ được điều kiện bắt buộc; chưa chốt ngưỡng. | Viết từng điều kiện thành hàm có mã lý do; tách dữ liệu thiếu khỏi dữ liệu không đạt. | P0 |
| MatchScore | Dễ giải thích; dễ lệch thang đo và tối ưu cục bộ. | Chuẩn hóa tiêu chí; công bố trọng số; so với greedy và bài toán phân bổ theo lô. | P0/P1 |
| Booking và ngoại lệ | Chưa đặc tả vòng đời và xử lý đồng thời. | State machine; hold có hạn; transaction; kiểm tra lại trước xác nhận. | P0 |
| ETA | Có tên Random Forest/LSTM; thiếu nhãn, baseline, sai số. | ETA luật khi thiếu dữ liệu; đánh giá theo thời gian trước khi dùng ML. | P1 |
| Thu nhận dữ liệu | Form/API/GPS chưa giải quyết mọi kênh nhập. | Thêm dán văn bản/PDF → bản nháp có nguồn → người duyệt; đo thời gian nhập. | P1 |
| Quản trị và bảo mật | Nguyên tắc tốt; thiếu cách thực thi. | RBAC \+ quyền theo lô; RLS; che trường nhạy cảm; kiểm thử truy cập chéo. | P0 |
| Audit và lợi ích | Có chủ trương lưu vết; chưa tái lập được quyết định. | Lưu snapshot, rule/model version, phê duyệt và baseline–actual theo chuyến. | P0 |
| Sustainability | Có MAC/intensity; số liệu và phạm vi chưa thống nhất. | Version hệ số phát thải; tách ước tính và đo thực; báo cáo cả CO₂ tuyệt đối. | P1 |

# **3\. Phạm vi sản phẩm**

## ***3.1. Prototype: chứng minh một luồng quyết định***

Phạm vi đề xuất: hàng khô; một hành lang khu công nghiệp–ICD; 10 xe, 20 lô, 20 slot; ba tổ chức; bốn vai trò shipper, carrier, node operator, điều phối viên. Dữ liệu seed để demo phải được gắn nhãn mô phỏng.

Sáu màn hình: nhập yêu cầu; danh sách xe/hàng; khuyến nghị và lý do; xác nhận/slot; timeline và ngoại lệ; bảng lợi ích theo chuyến. Bản đồ chỉ bổ trợ, không là điều kiện để demo thành công.

Slot tự tạo trong prototype là slot mô phỏng. Khi chưa có API hoặc người của ICD xác nhận, không hiển thị thành đặt chỗ thật.

## ***3.2. MVP: người dùng thật vận hành trong phạm vi hẹp***

Giữ một hành lang và hàng khô; có đối tác dữ liệu, người chịu trách nhiệm xác nhận, dữ liệu chuyến thật, phân quyền, khôi phục dữ liệu, theo dõi lỗi và phép đo đối chứng. MVP chứng minh quy trình được sử dụng lặp lại và tạo lợi ích đủ bù chi phí phục vụ.

Chưa nhận hàng lạnh, dược hoặc hàng nguy hiểm nếu chưa có quy trình chất lượng và điều kiện sẵn sàng riêng. Chưa dự báo lợi ích toàn mạng từ một mẫu pilot nhỏ.

# **4\. Kiến trúc và bộ công nghệ**

**Bảng 2\. Bộ công nghệ đề xuất cho nhóm dùng Python**

| Lớp | Chọn cho MVP | Cách triển khai / lý do |
| :---- | :---- | :---- |
| Giao diện | React \+ TypeScript \+ Vite | Một web responsive; trạng thái rõ; thông báo nguồn dữ liệu và tuổi dữ liệu. |
| Backend | FastAPI \+ Pydantic; SQLAlchemy \+ Alembic | API có schema; xác thực kiểu; migration DB; module intake, events, matching, booking, benefits. |
| Dữ liệu | PostgreSQL; PostGIS khi cần vị trí | DB giao dịch chính. Chỉ thêm PostGIS nếu cần lọc không gian; đường chim bay không thay thời gian lái xe. |
| Xử lý nền | Worker đọc jobs/outbox trong PostgreSQL | Dùng khóa/lease, retry có giới hạn, bảng lỗi và replay. Chưa cần Kafka hoặc nhiều broker. |
| Đăng nhập | Nhà cung cấp OIDC được quản lý | Không tự xây mật khẩu; backend kiểm tra token, tổ chức và quyền trên tài nguyên. |
| AI / tối ưu | scikit-learn; OR-Tools; một adapter LLM nếu có | ETA và parsing tách module; solver có timeout; phiên bản mô hình được ghi lại. |
| Tệp và vận hành | Object storage; container; CI/CD; telemetry | Tệp riêng tư; staging/production tách biệt; backup và thực tập restore. |
| Cập nhật giao diện | Polling trước; SSE nếu cần | Prototype cập nhật theo giây vừa đủ; tránh WebSocket khi chưa cần giao tiếp hai chiều. |

## ***4.1. Chuẩn dữ liệu và cơ chế xử lý sự kiện***

Làm schema nghiệp vụ tối thiểu tương thích hướng EPCIS, kèm adapter xuất/nhập. Không tự nhận “EPCIS compliant” nếu chưa kiểm tra theo chuẩn và trường hợp sử dụng. EPCIS chuẩn hóa sự kiện; SSCC nhận diện đơn vị logistics, không thay mọi loại ID \[1\].

Event tối thiểu: event\_id, schema\_version, tenant\_id, entity\_type, entity\_id, event\_type, occurred\_at, received\_at, source\_system, source\_event\_id, payload, quality\_status, correlation\_id.

- Lưu thời gian chuẩn UTC; giao diện hiển thị múi giờ vận hành. Giữ riêng occurred\_at và received\_at để đo độ trễ dữ liệu.  
- Ràng buộc duy nhất trên nguồn \+ source\_event\_id; endpoint nhận Idempotency-Key. Gửi lại một sự kiện không được tạo tác động nghiệp vụ lần hai.  
- Lưu sự kiện gốc; sự kiện sửa phải tham chiếu bản trước. Bản tin đến muộn không được tự kéo trạng thái từ completed về in\_transit.  
- Đổi trạng thái và ghi outbox trong cùng transaction. Worker retry; consumer idempotent; không hứa exactly-once end-to-end \[2\].  
- Mỗi đối tác có external\_id mapping. Khi gom/tách hàng, giữ quan hệ shipment–leg–logistics\_unit thay vì gán một mã cho mọi đối tượng.

## ***4.2. Bảng dữ liệu cần tạo***

organizations, users, memberships, shipments, shipment\_legs, logistics\_units, shipment\_participants, vehicles, availability\_windows, locations, slots, events, external\_id\_map, proposals, reservations, decisions, exceptions, benefit\_ledger, assumption\_sets, outbox\_jobs.

Dùng tenant\_id để cô lập dữ liệu; shipment\_participants và quyền theo vai trò để chia sẻ đúng lô giữa các doanh nghiệp. RLS là lớp bảo vệ bổ sung; tài khoản ứng dụng không có quyền bypass. Kiểm soát riêng trường giá, khách hàng và tệp vì RLS kiểm soát hàng dữ liệu, không tự che mọi trường \[3\].

# **5\. Sửa bộ máy quyết định để có thể lập trình và giải thích**

## ***5.1. Chuỗi xử lý bắt buộc***

Kiểm tra quyền và tuổi dữ liệu → lọc ứng viên gần phù hợp → hard gate → ước tính lợi ích → xếp hạng → giữ nguồn lực → xác nhận → kiểm tra lại → thực thi. Khi không có phương án đạt, trả “không có phương án khả thi” kèm lý do; không ép ghép.

Mỗi hard gate trả một trong PASS, FAIL, UNKNOWN và reason\_code. Trường bắt buộc UNKNOWN chuyển sang bổ sung dữ liệu; không âm thầm xem là PASS.

Ví dụ reason\_code: CARGO\_INCOMPATIBLE, CAPACITY\_EXCEEDED, PICKUP\_WINDOW\_MISSED, CUTOFF\_RISK, VEHICLE\_UNAVAILABLE, SLOT\_FULL, DATA\_STALE, ID\_UNRESOLVED.

Quy định rõ dữ liệu quá hạn theo use case. Ví dụ thử nghiệm: vị trí xe quá 5 phút thì không tự đề xuất một pickup sắp đến; sự kiện nghiệp vụ có SLA riêng. Ngưỡng này là cấu hình pilot, không là tiêu chuẩn chung.

## ***5.2. Tách khả thi, thứ hạng và lợi ích***

- Hard gate kiểm tra tải trọng/thể tích, điều kiện hàng, thời gian, phương tiện, slot và quyền sử dụng. Repositioning benefit chỉ là điều kiện cứng nếu đã có ngưỡng tối thiểu được phê duyệt.  
- MatchScore dùng tiêu chí đã đưa về thang 0-1; trọng số cộng bằng 1; quy định cách xử lý thiếu dữ liệu và tie-break. Tách điểm ưu tiên khỏi số tiền tiết kiệm.  
- Lưu input\_snapshot, candidate\_rejections, score\_components, rule\_version, model\_version, assumption\_version, expires\_at. Hiển thị lý do bằng template từ kết quả thực; LLM không được tự tạo lý do sau quyết định.  
- Xét chi phí đi vòng, chờ, bốc dỡ và rủi ro lỡ nhiệm vụ tiếp theo. Giảm km rỗng không mặc nhiên giảm tổng chi phí hoặc tổng phát thải.

Một màn hình khuyến nghị nên cho thấy: xe/lô/slot; ETA và độ bất định; từng điều kiện đã kiểm tra; 3 lý do chính; chi phí so sánh; dữ liệu dùng lúc nào; ai có quyền đồng ý.

## ***5.3. Phân bổ nhiều xe-hàng***

Prototype dùng greedy để có baseline dễ kiểm tra. MVP bổ sung OR-Tools cho phân bổ theo lô nhỏ, có ràng buộc mỗi xe/mỗi lô không bị cam kết trùng. Bài toán assignment thuần có thể dùng min-cost flow; khi có lịch, nhiều chặng và ràng buộc phức tạp, chọn CP-SAT/MIP phù hợp \[4\].

Bắt đầu mục tiêu tối thiểu tổng chi phí tăng thêm, phạt lô chưa phục vụ theo quy tắc công bố. Không đặt điều kiện mọi lô đều bắt buộc được gán nếu điều đó làm hệ thống không có nghiệm.

Giới hạn solver, ví dụ 2 giây với bộ thử 20 xe × 50 lô sau lọc. Khi timeout, dùng nghiệm khả thi đã kiểm tra hoặc greedy. Ghi trạng thái OPTIMAL/FEASIBLE/TIMEOUT; không gọi nghiệm FEASIBLE là tối ưu toàn cục.

## ***5.4. Booking phải là giao dịch có trạng thái***

Proposal: proposed → pending\_acceptance → confirmed → executing → completed; nhánh reject/expire/cancel. Reservation: held → committed hoặc released/expired.

Một hold có thời hạn, ví dụ 120 giây để thử nghiệm. Xác nhận cuối phải kiểm tra lại version, hạn hold, khả dụng xe, tải và slot trong transaction. Dùng row lock/constraint để chống hai người nhận cùng tài nguyên; slot có capacity thì cập nhật lượng còn lại một cách nguyên tử.

Nếu ICD dùng API bên ngoài, transaction DB không bao trùm được API đó. Lưu pending\_external, gọi qua outbox, retry theo khóa idempotency, đối soát và bù/giải phóng hold khi thất bại. Chỉ hiển thị confirmed\_external sau khi đối tác trả xác nhận.

Tách nguồn xác nhận node: mock, manual\_operator, partner\_api. Khi ETA thay đổi, proposal chưa cam kết có thể tính lại; chuyến đã thực hiện chỉ tạo ngoại lệ và xin quyết định phù hợp, không âm thầm chuyển xe.

# **6\. AI nên bổ sung ở đâu để tạo khác biệt?**

## ***6.1. AI nhập liệu có bằng chứng: ưu tiên khi đối tác chưa có API***

Cho phép dán tin nhắn hoặc tải một PDF văn bản/ảnh phiếu do người dùng cung cấp. AI trích xuất thành bản nháp; người dùng kiểm tra rồi mới tạo yêu cầu có hiệu lực. Không tự kết nối tài khoản Zalo, ghi âm cuộc gọi hoặc lấy dữ liệu khi chưa có quyền.

Luồng: tệp gốc → trích văn bản/OCR nếu cần → LLM theo schema JSON → kiểm tra kiểu, đơn vị, mốc giờ → hiển thị nguồn theo trường → người dùng xác nhận → lưu sự kiện.

* Trường thiếu trả null/needs\_review; ngày “mai” phải giải theo thời điểm nguồn và múi giờ, yêu cầu xác nhận nếu mơ hồ.  
* Lưu trích đoạn hoặc vị trí nguồn cho điểm lấy/giao, thời gian, tải, loại hàng. Dùng rule kiểm tra, không tin điểm confidence do LLM tự khai.  
* Tệp là dữ liệu không tin cậy: không làm theo chỉ dẫn nằm trong tệp; giới hạn loại/kích thước; không cho mô hình quyền xác nhận booking hoặc sửa DB trực tiếp \[6\].  
* Đo độ chính xác từng trường trên tập đối chiếu do người dùng nghiệp vụ duyệt; đo thời gian sửa và tỷ lệ nhập thành công. Chỉ mở rộng nếu tiết kiệm công thao tác đủ bù API/OCR và chi phí kiểm tra.

MVP có thể bắt đầu bằng văn bản và PDF có text. OCR ảnh, giọng nói và tích hợp kênh nhắn tin là các bước sau theo nhu cầu được khảo sát.

## ***6.2. ETA có benchmark và cơ chế dự phòng***

Cold start: ETA từ bảng tuyến–khung giờ đã duyệt cộng thời gian xử lý; nếu dùng API định tuyến phải ghi nhà cung cấp, cache và hạn dữ liệu. Gắn nhãn rule-based, không trình bày như ML đã huấn luyện.

Khi có đủ chuyến hoàn tất đại diện cho hành lang, train Random Forest hoặc một mô hình bảng khác và so với median theo tuyến/khung giờ. Không chốt số chuyến cố định để bảo đảm chất lượng; dùng learning curve và sai số theo từng nhóm.

* Nhãn là actual\_arrival\_at − prediction\_time; mỗi feature phải tồn tại tại prediction\_time. Lưu features/model/version tại lúc dự báo.  
* Chia train/validation/test theo thời gian; nhóm snapshot của cùng chuyến để tránh rò rỉ. Dữ liệu mô phỏng chỉ kiểm thử pipeline, không chứng minh độ chính xác thực tế \[5\].  
* Báo MAE phút, P90 sai số và tỷ lệ đến trong ±15 phút tại cùng chân trời dự báo, chẳng hạn trước 60 phút. Tách theo tuyến và giờ cao điểm.  
* Đưa ML vào sử dụng nếu cải thiện baseline trên tập giữ lại và không làm xấu quyết định vận hành. Có thể đặt mục tiêu thử MAE giảm ≥15%; đây là gate đề xuất, không phải kết quả cam kết.

Chỉ công bố khoảng dự báo P50/P90 khi đã đánh giá độ bao phủ. Khi dữ liệu thiếu, mô hình lỗi hoặc drift, hạ về ETA luật và hiển thị độ tin cậy thấp.

# **7\. API, giao diện và trách nhiệm người dùng**

POST /v1/intake/drafts \- tạo nháp từ văn bản/tệp; POST /v1/shipments \- xác nhận yêu cầu hợp lệ.

POST /v1/events \- nhận sự kiện idempotent; GET /v1/shipments/{id}/timeline \- dữ liệu theo quyền.

POST /v1/match-runs \- tạo lượt đề xuất; GET /v1/proposals/{id} \- lý do, snapshot và hạn đề xuất.

POST /v1/proposals/{id}/hold; POST /v1/proposals/{id}/accept; POST /v1/proposals/{id}/reject \- có version và Idempotency-Key.

POST /v1/exceptions/{id}/resolve; GET /v1/benefits?scope=... \- xử lý ngoại lệ và xuất lợi ích theo phạm vi.

Các nút xác nhận phải phản ánh đúng quyền: carrier nhận việc, shipper duyệt thay đổi lô, node duyệt slot. Điều phối viên không mặc định có quyền thay tất cả. Mỗi API đọc/ghi đều kiểm tra quyền; ẩn nút trên giao diện chưa đủ.

Trên màn hình lợi ích, tách estimated, measured, verified. Hiển thị mock/live, tuổi dữ liệu và nguồn xác nhận ở nơi người dùng ra quyết định.

# **8\. Kế hoạch prototype trong 5 ngày làm việc**

**Bảng 3\. Năm ngày tạo bản demo có thể kiểm tra**

| Ngày | Làm gì | Sản phẩm bàn giao | Điều kiện qua |
| :---- | :---- | :---- | :---- |
| 1 | Chốt schema, vai trò, seed; dựng UI/API/DB và CI. | 20 lô, 10 xe, 20 slot; ba tài khoản tổ chức. | Tạo/đọc lô; tổ chức A không đọc lô riêng B. |
| 2 | Viết hard gate, score và phép tính chi phí; giao diện giải thích. | Candidate list và reason\_code; thông số có version. | Loại đúng xe thiếu tải, sai hàng, trễ giờ; input thiếu bị chặn. |
| 3 | Hold/accept/reject, hết hạn và slot có capacity. | Một luồng xác nhận chạy đến completed. | Hai lần nhận đồng thời: chỉ một thành công; event gửi lại không nhân đôi. |
| 4 | Timeline, ngoại lệ, replay và benefit ledger; AI nháp nếu lõi đã qua. | ETA đổi → ngoại lệ; so sánh baseline–actual; nháp có nguồn. | Không tự sửa chuyến đã cam kết; parsing thiếu trường không tạo lô hiệu lực. |
| 5 | Chạy test lỗi, seed/reset và đóng gói demo. | Link staging, hướng dẫn chạy, test report và video 3–5 phút. | Sáu kịch bản lặp lại được; mọi số mô phỏng được gắn nhãn. |

Nếu thiếu người hoặc thời gian, bỏ AI nháp ngày 4 trước; giữ xử lý xác nhận, dữ liệu lỗi và truy vết. Không thay phần lõi bằng nút bấm tạo kết quả cố định.

# **9\. Kế hoạch MVP và pilot theo gate**

Ước lượng MVP: 10 tuần với một frontend, một backend, một data/optimization engineer và QA/điều phối nghiệp vụ bán thời gian. Thiếu đối tác hoặc dữ liệu sẽ kéo dài lịch; ký quyền sử dụng dữ liệu và bố trí đầu mối xác nhận trước khi vào pilot.

**Bảng 4\. Lộ trình từ sản phẩm hẹp đến mở rộng**

| Giai đoạn | Đầu việc | Bằng chứng bàn giao | Gate |
| :---- | :---- | :---- | :---- |
| Tuần 1–2 | Khảo sát luồng thật, mapping ID, bộ sự kiện, baseline và quyền. | Data dictionary; mẫu dữ liệu; quy trình ngoại lệ; trách nhiệm dữ liệu. | G1: xác định được nguồn và chủ sở hữu từng trường bắt buộc. |
| Tuần 3–4 | API/events; phân quyền; booking/outbox; nhập CSV; backup. | Luồng dữ liệu từ ít nhất một đối tác; test đồng thời và restore. | Qua toàn bộ test an toàn vận hành quan trọng. |
| Tuần 5–6 | Matching, baseline, OR-Tools; AI nháp theo nhu cầu. | Báo so sánh greedy/solver; chi phí mỗi đề xuất; bộ parsing đối chiếu. | Không vi phạm hard gate; không phân bổ trùng. |
| Tuần 7–8 | ETA nếu dữ liệu đủ; observability; benefit ledger; UAT. | Model card hoặc ETA luật; dashboard lỗi; UAT theo vai trò. | Quyết định tái lập được; dữ liệu chưa đủ thì giữ ETA luật. |
| Tuần 9–10 | Shadow mode, sửa lỗi và đào tạo; chọn nhóm thực hiện nhỏ. | Đề xuất chạy song song quy trình cũ; log chấp nhận/từ chối. | Đối tác ký nghiệm thu phạm vi; rollback chạy được. |
| Pilot 8–12 tuần tiếp | Canary, theo dõi chuyến thực; đối chứng cùng hành lang. | Lợi ích verified; chi phí phục vụ; tỷ lệ quay lại dùng. | G2 vận hành, G3 kinh tế, G4 nghĩa vụ dữ liệu cùng đạt. |

Gắn với chiến lược gốc: 2026–2027 Standardize/Measure dùng phạm vi hẹp trên; 2028–2029 chỉ thêm nhánh khi dữ liệu, năng lực tích hợp và lợi ích nhánh trước đã qua gate; 2030 mới xem xét tối ưu đa hành lang và mô phỏng theo nhu cầu.

Cold chain chỉ mở sau khi có telemetry đáng tin, hiệu chuẩn/kiểm tra cảm biến, ngưỡng nhiệt theo mặt hàng, thời lượng excursion và người quyết định xử lý chất lượng. Cảnh báo nhiệt không tự quyết định hủy hoặc giải phóng hàng.

# **10\. Bộ kiểm thử và chỉ số nghiệm thu**

Các ngưỡng hiệu năng dưới đây là mục tiêu ban đầu cho phạm vi thử, phải ghi rõ cấu hình máy, tải đồng thời và dữ liệu. Không dùng chúng làm cam kết SLA toàn mạng.

**Bảng 5\. Những gì phải đo trước khi mở rộng**

| Nhóm | Cách đo / mục tiêu đề xuất | Bằng chứng |
| :---- | :---- | :---- |
| Tính đúng quyết định | 100% case hard gate quan trọng qua; không có gán tài nguyên trùng. | Test tự động trên bộ dữ liệu và race test. |
| Sự kiện | Một event gửi lặp 10 lần chỉ có một tác động; replay không gửi lại tác động ngoài. | DB state, outbox/inbox và log. |
| Phân quyền | Không truy cập trái phép qua API, DB role, file URL, export và AI context. | Test A/B tenant cho đọc, sửa, list, tải tệp. |
| Hiệu năng | Match P95 \<2 giây cho 20 xe ×50 lô; loại thời gian API bên ngoài và báo riêng. | Load test tái lập; timeout và fallback. |
| Dữ liệu pilot | ID continuity ≥98%; full mandatory events ≥95%; P95 latency ≤15 phút theo slide. | Đo trên tất cả lô trong phạm vi, kể cả lô thiếu sự kiện. |
| ETA / AI nhập liệu | ETA thắng baseline ngoài mẫu; parsing đo đúng từng trường và thời gian sửa. | Tập test khóa trước; báo sai số và số mẫu. |
| Khôi phục | Đề xuất MVP: RPO ≤24 giờ, RTO ≤4 giờ; backup hằng ngày. | Thực tập restore; nếu vận hành cần tốt hơn thì nâng trước live. |
| Kinh tế và sử dụng | Tiết kiệm verified; cost/completed lot; tỷ lệ accepted/completed; phút thao tác. | Đối tác xác nhận; so sánh theo tuyến, hàng, tải và thời kỳ. |

Sáu kịch bản demo bắt buộc: ghép thành công; xe không tương thích bị loại; dữ liệu quá hạn; hai người giữ cùng tài nguyên; ETA đổi làm phương án cũ không còn phù hợp; sự kiện trùng/worker restart. Thêm tệp có chỉ dẫn giả nếu bật LLM.

Đo hệ thống bằng trace\_id/correlation\_id, log có cấu trúc, tỷ lệ lỗi, độ trễ hàng đợi, tuổi sự kiện và số job thất bại. OpenTelemetry hỗ trợ traces, metrics và logs; thiết kế dashboard theo sự cố nghiệp vụ, không chỉ CPU \[7\].

Audit nghiệp vụ và log kỹ thuật là hai loại khác nhau. Append-only ở ứng dụng chưa bảo đảm bất biến tuyệt đối: hạn quyền DB, sao lưu tách biệt và dùng object lock/kiểm tra can thiệp khi cần. Không đưa dữ liệu hàng/khách hàng nhạy cảm vào metric label hoặc log mặc định.

# **11\. Sửa mô hình kinh tế bằng chính các chức năng phần mềm**

## ***11.1. Tạo benefit ledger thay cho tổng tiết kiệm trên dashboard***

Mỗi chuyến hoàn tất có baseline đã chốt trước quyết định, actual, đơn vị, nguồn, người hưởng lợi, bằng chứng và mức xác minh. Baseline chọn sau khi biết kết quả sẽ làm số tiết kiệm thiếu tin cậy.

Benefit record: shipment\_id, baseline\_id, cost\_category, quantity\_before, quantity\_after, unit\_rate, currency, assumption\_version, beneficiary\_org\_id, evidence\_refs, status, verifier, verified\_at.

Lợi ích ròng một chuyến \= chi phí phương án đối chứng − chi phí thực hiện − chi phí tăng thêm chưa nằm trong chi phí thực hiện. Ghi rõ phần đi vòng, chờ và xử lý; không trừ cùng chi phí hai lần.

Một event thiệt hại có mã duy nhất. Tách giá trị hàng tránh mất khỏi chi phí vận chuyển/xử lý hoàn để không đếm trùng. Khoản 104,7 tỷ vốn lưu động giải phóng phải tách khỏi dòng tiết kiệm lặp lại 20,9 tỷ/năm \[8\].

## ***11.2. Phân biệt giá trị mạng lưới với doanh thu vận hành***

79,6 tỷ/năm trong slide là pool ước tính của nhiều bên, không phải doanh thu Tower. Phần mềm phải cho biết khoản nào carrier hưởng, khoản nào chủ hàng hưởng và khoản nào có thể thu phí.

MVP thử một mô hình thu: phí thuê bao điều phối \+ phí tích hợp ban đầu; chỉ thử success fee khi có baseline được hai bên chấp nhận. Đo willingness-to-pay qua cam kết pilot/trả phí thực, không suy từ tổng pool.

Contribution/tháng \= doanh thu thực thu − cloud/API/OCR theo sử dụng − hỗ trợ vận hành biến đổi − các chi phí biến đổi khác.

Báo riêng chi phí onboarding mỗi đối tác, số tuần đến lô compliant đầu tiên và tỷ lệ khách tiếp tục dùng. Adapter chuẩn, mapping nhập lại được và form nhập nhẹ giúp giảm chi phí này.

## ***11.3. Tách ba bảng tính và gắn phiên bản giả định***

* Bảng A: economics theo lô \- cước, thời gian, rủi ro, xử lý, đơn vị đồng nhất; giá nhạy cảm chỉ cho chủ thể được phép xem.  
* Bảng B: hiệu quả chương trình \- CAPEX/OPEX, dòng tiền theo tháng, ramp-up, phạm vi 15 tỷ so với 52,03 tỷ, BCR/NPV và thời điểm hoàn vốn.  
* Bảng C: sustainability \- nhiên liệu/quãng đường hoặc tấn-km, hệ số phát thải có nguồn, phần đo và phần ước tính, tuyệt đối và cường độ.

Nếu đã ghi CAPEX trong dòng tiền, không tiếp tục trừ khấu hao như một khoản chi tiền mới; chỉ xử lý ảnh hưởng thuế phù hợp nếu mô hình có thuế \[8\]. Payback 11,8 tháng cần ghi rõ có bao gồm 8 tháng thiết lập hay không; không dùng kết quả giản đơn thay cho dòng tiền chiết khấu.

Chốt một bộ baseline CO₂, sửa chênh lệch 677/571 tCO₂e và 0,1117/0,1122 giữa các trang. MAC phải có chi phí và lượng giảm cùng thời kỳ; giải thích phần lợi ích nào được phân bổ vào MAC.

Sửa biểu đồ ngưỡng air/sea-air để cùng chiều với công thức. Định nghĩa phần trăm chênh TLC bằng một mẫu số cụ thể. Các mức 266/581/710/912 USD/kg phải có assumption\_set tái lập, không hard-code trong UI.

# **12\. Đổi phần nào trong slide và demo để tăng sức thuyết phục? (slide fix)**

* Slide kiến trúc: thay danh sách tên thuật toán bằng module, input/output, nơi lưu dữ liệu, chủ thể xác nhận và cơ chế fallback.  
* Slide AI: tách đã chạy, đang thử và tương lai. Cho xem một bản nháp có dẫn nguồn hoặc benchmark ETA thực; ghi rõ dữ liệu mô phỏng.  
* Slide matching: thêm một ví dụ bị loại đúng, một ví dụ hai xe–hai lô mà greedy kém hơn phân bổ theo lô, và cách xử lý không có nghiệm.  
* Slide governance: minh họa tổ chức A không đọc giá/tệp của B; một đề xuất chỉ hiện dữ liệu đủ dùng; mọi accept có actor, version và thời điểm.  
* Slide kinh tế: cho mở một chuyến từ số tiết kiệm đến bằng chứng và assumption. Tách tiềm năng, estimated và verified; không phóng đại từ kết quả demo.  
* Slide roadmap: ghi deliverable và gate cho từng bước; thay “năm sau dùng LSTM” bằng điều kiện dữ liệu và mức cải thiện đủ bù chi phí.

Kịch bản trình diễn 4 phút: 40 giây nhập yêu cầu và kiểm nguồn; 60 giây chọn/loại ứng viên; 60 giây carrier và node xác nhận; 40 giây tạo trễ hoặc dữ liệu lỗi; 40 giây mở sổ lợi ích và audit. Mỗi màn hình trả lời một câu hỏi kinh doanh.

# **13\. Backlog giao việc ngay**

* P0-01 \- Product/Operations: chốt một hành lang, đơn vị đo, mandatory events, baseline và quyền xác nhận. Bàn giao data dictionary và sáu kịch bản UAT.  
* P0-02 \- Backend: schema, migration, ID mapping, event idempotency và outbox. Nghiệm thu bằng gửi trùng, đến sai thứ tự và restart worker.  
* P0-03 \- Backend/QA: state machine, hold/expiry, kiểm tra lại và chống nhận trùng. Nghiệm thu bằng hai yêu cầu đồng thời.  
* P0-04 \- Frontend/Backend: phân quyền tổ chức và theo lô, tệp riêng tư, audit. Nghiệm thu bằng API trực tiếp, không chỉ UI.  
* P0-05 \- Data/Operations: TLC chuẩn đơn vị, benefit ledger và assumption version. Một chuyến phải tái lập được từ dữ liệu gốc.  
* P1-01 \- Frontend/Data: nhập nháp có nguồn; kiểm schema và người duyệt. Chỉ triển khai khi có nhu cầu nhập liệu thực.  
* P1-02 \- Data: ETA baseline, split theo thời gian, benchmark và fallback; chỉ promote mô hình khi qua gate.  
* P1-03 \- Data/Backend: OR-Tools và replay; so nghiệm cùng input, cùng constraint; timeout không phá luồng vận hành.

Thứ tự đầu tư: dữ liệu và giao dịch đúng → vòng điều phối có người dùng thật → lợi ích verified → AI/tối ưu tăng thêm. Mỗi lần nâng độ phức tạp phải trả lời được chi phí mới đổi lấy kết quả nào.

# **14\. Nguồn kỹ thuật và căn cứ**

Cơ sở dự án: 5changlinhngulam.pdf và bản chuyển nội dung 5changlinhngulam.md. Tài liệu này là đề xuất kiến trúc/triển khai; các lựa chọn stack và gate do người đánh giá đề xuất, không phải tính năng đã được xác nhận trong mã nguồn.

[\[1\] GS1 \- EPCIS và dữ liệu sự kiện; dùng làm căn cứ thiết kế schema, không thay đánh giá tương thích chuẩn.](https://support.gs1.org/support/solutions/articles/43000755325-what-is-electronic-product-code-information-services-epcis-)

[\[2\] AWS \- Transactional outbox; ghi dữ liệu và sự kiện nhất quán, xử lý gửi trùng.](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)

[\[3\] PostgreSQL \- Row Security Policies; phạm vi và ngoại lệ quyền truy cập theo hàng.](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

[\[4\] Google OR-Tools \- Assignment; lựa chọn MIP/CP-SAT cho bài toán phân bổ.](https://developers.google.com/optimization/assignment/assignment_example)

[\[5\] scikit-learn \- Data leakage và quy trình đánh giá mô hình.](https://scikit-learn.org/stable/common_pitfalls)

[\[6\] OWASP \- Excessive Agency; hạn chế quyền và hành động của hệ thống LLM.](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)

[\[7\] OpenTelemetry \- Signals; giám sát traces, metrics và logs.](https://opentelemetry.io/docs/concepts/signals/)

[\[8\] ATAP \- Xác định lợi ích/chi phí; tránh đếm trùng và phân biệt khấu hao.](https://www.atap.gov.au/tools-techniques/cost-benefit-analysis/3-step-2-identify-the-benefits-and-costs)

