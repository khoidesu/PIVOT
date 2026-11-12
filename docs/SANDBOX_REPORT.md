# Sandbox mô phỏng lợi ích — 100 trường hợp (seed 42)

> **MÔ PHỎNG — không phải lợi ích đã xác minh.** Dữ liệu do nhóm tự sinh (phân phối tự định nghĩa), chạy đúng đường code thật của hệ thống (hard gate + MatchScore + ETA luật). Kết quả chỉ chứng minh **cách tính và hướng tác động**, không chứng minh độ lớn ngoài đời thật (DRAFT 6.2).

- Phiên bản: `rules-v1` · giả định `assume-v2` · hồ sơ `mixed` · sinh lúc 2026-11-13T00:27:49.162101+07:00
- Khả thi: **87/100** ca (13 ca không có xe nào qua hard gate — được đếm riêng, **không ép ghép**); trung bình 6.3 xe qua hard gate mỗi ca.

## 1. Xe điểm cao nhất (top-1) — kết quả trung bình

| Chỉ số | Giá trị |
|---|---|
| Km chạy rỗng | 11.8 km |
| Chi phí chạy rỗng | 165,184 VND |
| Phút tới điểm lấy | 54.8 phút |
| Phút tới ICD | 174.6 phút |
| Trễ hạn lấy hàng (thực tế mô phỏng) | 0.0% |
| Trễ cut-off (thực tế mô phỏng) | 0.0% |
| Cờ cảnh báo cut-off P90 của hệ thống | 0.0% |

So với baseline tĩnh của hành lang (38 km chạy rỗng): tiết kiệm trung bình **26.2 km ≈ 366,816 VND/chuyến**; top-1 tốt hơn baseline ở 100% số ca. *(Baseline là giả định cấu hình, không phải đo thực.)*

## 2. Top-1 so với cách chọn khác (chênh lệch cặp; DƯƠNG = top-1 tốt hơn)

Mỗi dòng: chênh lệch trung bình [khoảng tin cậy 95% bootstrap] · tỷ lệ ca top-1 không tệ hơn.

### vs chọn ngẫu nhiên (kỳ vọng)

| Chỉ số | Chênh lệch TB [CI 95%] | Trung vị | p10 – p90 | Tỷ lệ thắng |
|---|---|---|---|---|
| Km chạy rỗng (km) | 3.0 [2.4; 3.6] | 3.7 | -0.6 – 6.5 | 89% |
| Chi phí chạy rỗng (VND) | 41,849 [32,183; 50,330] | 51,240 | -8,680 – 90,434 | 89% |
| Phút tới điểm lấy (phút) | 13.4 [10.3; 16.4] | 9.5 | 0.0 – 34.3 | 92% |
| Phút tới ICD (phút) | 12.5 [9.3; 15.9] | 11.2 | -4.5 – 34.1 | 77% |

Chênh tỷ lệ trễ (cách khác − top-1): lấy hàng +1.0 điểm %, cut-off +0.2 điểm %.

### vs xe gần nhất

| Chỉ số | Chênh lệch TB [CI 95%] | Trung vị | p10 – p90 | Tỷ lệ thắng |
|---|---|---|---|---|
| Km chạy rỗng (km) | -1.2 [-1.7; -0.7] | 0.0 | -4.2 – 0.0 | 77% |
| Chi phí chạy rỗng (VND) | -16,446 [-24,750; -9,429] | 0 | -59,360 – 0 | 77% |
| Phút tới điểm lấy (phút) | 6.7 [3.0; 10.7] | 0.0 | 0.0 – 29.7 | 92% |
| Phút tới ICD (phút) | 6.7 [3.0; 11.0] | 0.0 | -0.6 – 27.8 | 87% |

Chênh tỷ lệ trễ (cách khác − top-1): lấy hàng +1.1 điểm %, cut-off +0.0 điểm %.

### vs xe đầu danh sách

| Chỉ số | Chênh lệch TB [CI 95%] | Trung vị | p10 – p90 | Tỷ lệ thắng |
|---|---|---|---|---|
| Km chạy rỗng (km) | 3.2 [2.3; 4.2] | 2.2 | 0.0 – 9.8 | 92% |
| Chi phí chạy rỗng (VND) | 44,832 [31,411; 57,675] | 30,800 | 0 – 137,200 | 92% |
| Phút tới điểm lấy (phút) | 15.7 [10.0; 21.6] | 0.0 | -0.3 – 61.0 | 90% |
| Phút tới ICD (phút) | 14.8 [9.3; 20.9] | 1.4 | -9.5 – 58.8 | 78% |

Chênh tỷ lệ trễ (cách khác − top-1): lấy hàng +1.1 điểm %, cut-off +0.0 điểm %.

## 3. Giá trị của hard gate

Nếu chọn xe đầu danh sách **không qua hard gate**: 58% số ca rơi vào xe không đủ điều kiện (quá tải / sai loại hàng / trễ giờ / dữ liệu cũ / offline); trung bình 61% đội xe không đạt.

## 4. Độ nhạy theo hồ sơ

| Hồ sơ | Ca khả thi | km top-1 | Tiết kiệm km vs ngẫu nhiên | Tiết kiệm phút tới ICD vs ngẫu nhiên |
|---|---|---|---|---|
| đô thị dày | 33/34 | 9.2 | 3.8 | 12.7 |
| giờ cao điểm | 29/33 | 11.5 | 3.4 | 10.8 |
| thưa | 25/33 | 15.5 | 1.4 | 14.2 |

Top-1 trùng xe gần nhất ở 53% số ca; khi không trùng, top-1 chạy rỗng **nhiều km hơn** xe gần nhất (điểm cân bằng độ vừa tải + dư thời gian + km) nhưng tới ICD sớm hơn — xem mục 2.

## 5. Giới hạn (đọc kỹ)

- Phân phối lô/đội xe/bãi/khung rảnh, tỷ lệ xe quá hạn/offline, nhiễu thời gian đều do nhóm đặt — đổi giả định sẽ đổi con số. Hồ sơ `peak` và `sparse` cho thấy độ nhạy.
- 'Thực tế' = ETA luật × nhiễu mô phỏng (cùng phân phối với lịch sử ETA mô phỏng), tách khỏi dự báo; vẫn chưa phải đo từ chuyến thật.
- Tỷ lệ trễ hạn rất thấp ở mọi cách chọn vì hạn lấy hàng/cut-off trong kịch bản khá rộng; lợi ích chính hiện ở **km rỗng, chi phí, và phút tới ICD**.
- Chi phí = km rỗng × đơn giá cấu hình (14.000 VND/km); chưa gồm chi phí chờ, phạt trễ, nhiên liệu theo tải.
- Không ghi vào sổ lợi ích thật; không thay thế việc xác minh độc lập bằng số đo từ chuyến hoàn tất.
