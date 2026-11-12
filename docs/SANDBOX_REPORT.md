# Sandbox mô phỏng lợi ích — 100 trường hợp (seed 42)

> **MÔ PHỎNG — không phải lợi ích đã xác minh.** Dữ liệu do nhóm tự sinh (phân phối tự định nghĩa), chạy đúng đường code thật của hệ thống (hard gate + MatchScore + ETA luật). Kết quả chỉ chứng minh **cách tính và hướng tác động**, không chứng minh độ lớn ngoài đời thật (DRAFT 6.2).

- Phiên bản: `rules-v1` · giả định `assume-v2` · hồ sơ `mixed` · sinh lúc 2026-11-13T00:52:30.280407+07:00
- Khả thi: **94/100** ca (6 ca không có xe nào qua hard gate — được đếm riêng, **không ép ghép**); trung bình 5.6 xe qua hard gate mỗi ca.

## 1. Xe điểm cao nhất (top-1) — kết quả trung bình

| Chỉ số | Giá trị |
|---|---|
| Km chạy rỗng | 2.3 km |
| Chi phí chạy rỗng | 31,798 VND |
| Phút tới điểm lấy | 48.8 phút |
| Phút tới ICD | 169.0 phút |
| Trễ hạn lấy hàng (thực tế mô phỏng) | 0.0% |
| Trễ cut-off (thực tế mô phỏng) | 0.0% |
| Cờ cảnh báo cut-off P90 của hệ thống | 0.0% |

So với baseline tĩnh của hành lang (38 km chạy rỗng): tiết kiệm trung bình **35.7 km ≈ 500,202 VND/chuyến**; top-1 tốt hơn baseline ở 100% số ca. *(Baseline 38 km là giả định cấu hình, không phải đo thực; mô hình nhà xe giả định mọi xe rảnh đậu trong bán kính 5 km quanh điểm lấy hàng, nên phần lớn chênh lệch này đến từ chính giả định đó — đừng đọc nó như lợi ích của riêng việc chọn xe điểm cao nhất; so sánh có ý nghĩa là mục 2.)*

## 2. Top-1 so với cách chọn khác (chênh lệch cặp; DƯƠNG = top-1 tốt hơn)

Mỗi dòng: chênh lệch trung bình [khoảng tin cậy 95% bootstrap] · tỷ lệ ca top-1 không tệ hơn.

### vs chọn ngẫu nhiên (kỳ vọng)

| Chỉ số | Chênh lệch TB [CI 95%] | Trung vị | p10 – p90 | Tỷ lệ thắng |
|---|---|---|---|---|
| Km chạy rỗng (km) | 0.4 [0.2; 0.5] | 0.2 | -0.4 – 1.5 | 73% |
| Chi phí chạy rỗng (VND) | 5,290 [3,275; 7,473] | 2,660 | -5,145 – 21,004 | 73% |
| Phút tới điểm lấy (phút) | 5.9 [3.7; 8.3] | 2.3 | 0.0 – 21.1 | 91% |
| Phút tới ICD (phút) | 5.5 [2.9; 8.1] | 3.0 | -8.4 – 23.7 | 74% |

Chênh tỷ lệ trễ (cách khác − top-1): lấy hàng +0.0 điểm %, cut-off +0.0 điểm %.

### vs xe gần nhất

| Chỉ số | Chênh lệch TB [CI 95%] | Trung vị | p10 – p90 | Tỷ lệ thắng |
|---|---|---|---|---|
| Km chạy rỗng (km) | -0.5 [-0.7; -0.4] | 0.0 | -1.6 – 0.0 | 53% |
| Chi phí chạy rỗng (VND) | -7,134 [-9,398; -4,900] | 0 | -21,980 – 0 | 53% |
| Phút tới điểm lấy (phút) | 5.6 [2.1; 9.3] | 0.0 | 0.0 – 25.1 | 94% |
| Phút tới ICD (phút) | 6.3 [2.3; 10.6] | 0.0 | -10.0 – 26.8 | 78% |

Chênh tỷ lệ trễ (cách khác − top-1): lấy hàng +0.0 điểm %, cut-off +0.0 điểm %.

### vs xe đầu danh sách

| Chỉ số | Chênh lệch TB [CI 95%] | Trung vị | p10 – p90 | Tỷ lệ thắng |
|---|---|---|---|---|
| Km chạy rỗng (km) | 0.4 [0.2; 0.6] | 0.0 | -0.4 – 2.0 | 87% |
| Chi phí chạy rỗng (VND) | 5,198 [2,309; 8,445] | 0 | -5,180 – 27,580 | 87% |
| Phút tới điểm lấy (phút) | 5.7 [2.1; 9.1] | 0.0 | 0.0 – 27.6 | 95% |
| Phút tới ICD (phút) | 6.2 [2.4; 10.6] | 0.0 | -6.9 – 31.2 | 73% |

Chênh tỷ lệ trễ (cách khác − top-1): lấy hàng +0.0 điểm %, cut-off +0.0 điểm %.

## 3. Giá trị của hard gate

Nếu chọn xe đầu danh sách **không qua hard gate**: 65% số ca rơi vào xe không đủ điều kiện (quá tải / sai loại hàng / trễ giờ / dữ liệu cũ / offline); trung bình 62% đội xe không đạt.

## 4. Độ nhạy theo hồ sơ

| Hồ sơ | Ca khả thi | km top-1 | Tiết kiệm km vs ngẫu nhiên | Tiết kiệm phút tới ICD vs ngẫu nhiên |
|---|---|---|---|---|
| đô thị dày | 33/34 | 2.2 | 0.6 | 7.5 |
| giờ cao điểm | 33/33 | 2.1 | 0.5 | 5.5 |
| thưa | 28/33 | 2.6 | 0.1 | 3.2 |

Top-1 trùng xe gần nhất ở 35% số ca; khi không trùng, top-1 chạy rỗng **nhiều km hơn** xe gần nhất (điểm cân bằng độ vừa tải + dư thời gian + km) nhưng tới ICD sớm hơn — xem mục 2.

## 5. Giới hạn (đọc kỹ)

- Mô hình nhà xe: mỗi nhà xe có MỘT bãi trong bán kính 5 km quanh điểm lấy hàng và xe rảnh luôn ở đó — nên các xe vốn đã gần nhau và mức tiết kiệm km giữa các cách chọn nhỏ; lợi ích lớn hơn nếu đội xe thật rải rộng hơn.
- Phân phối lô/đội xe/bãi/khung rảnh, tỷ lệ xe quá hạn/offline, nhiễu thời gian đều do nhóm đặt — đổi giả định sẽ đổi con số. Hồ sơ `peak` và `sparse` cho thấy độ nhạy.
- 'Thực tế' = ETA luật × nhiễu mô phỏng (cùng phân phối với lịch sử ETA mô phỏng), tách khỏi dự báo; vẫn chưa phải đo từ chuyến thật.
- Tỷ lệ trễ hạn rất thấp ở mọi cách chọn vì hạn lấy hàng/cut-off trong kịch bản khá rộng; lợi ích chính hiện ở **km rỗng, chi phí, và phút tới ICD**.
- Chi phí = km rỗng × đơn giá cấu hình (14.000 VND/km); chưa gồm chi phí chờ, phạt trễ, nhiên liệu theo tải.
- Không ghi vào sổ lợi ích thật; không thay thế việc xác minh độc lập bằng số đo từ chuyến hoàn tất.
