# Đặc tả bộ dữ liệu ETA mô phỏng (để huấn luyện trên Kaggle)

> **Cập nhật 12/11/2026:** dữ liệu đã được sinh theo đặc tả này bằng `backend/app/eta_data_gen.py` → `data/eta/`. Các câu hỏi ở mục 10 được chốt theo mặc định: 20k chuyến · giữ drift (`--no-drift` để tắt) · 2 tuyến + 3 hạng xe · baseline `rule_dist_min` + `baseline_median_min` · chỉ dự báo lúc xuất phát · mưa/gió dạng số · quãng đường sinh quanh 22 km (tuyến A) và 28 km (tuyến B), cắt ở 8–40 km.

> **Trạng thái: chưa sinh dữ liệu.** File này mô tả *chính xác* những gì sẽ có trong CSV. Bạn duyệt/sửa xong thì mới sinh dữ liệu.
> Mọi số liệu là **MÔ PHỎNG** (do bộ sinh có hạt giống cố định tạo ra). Mô hình train trên đó chỉ chứng minh **quy trình** (chia theo thời gian, cổng promote, tự hạ về luật), **không** chứng minh độ chính xác ngoài đời (DRAFT 6.2). Giao diện giữ nhãn "lịch sử mô phỏng".

## 1. Bài toán

Dự báo **thời gian trung chuyển thực tế** (phút) từ lúc xe **rời điểm lấy hàng** đến lúc **tới cổng ICD**, **tại thời điểm xuất phát**, chỉ dùng thông tin biết trước lúc đó. Cần **hai đầu ra**: **P50** (trung vị) và **P90** (mốc 90% chuyến đến kịp). Hệ thống dùng cả hai (P50 cho ETA, P90 cho cảnh báo mềm cut-off).

- Đây là cùng bài toán mà `app/eta/ml.py` đang giải (đầu vào: quãng đường, giờ, thứ, mưa), nhưng dữ liệu phong phú hơn và có baseline mạnh hơn để so.
- Chưa làm: dự báo giữa đường (khi xe đã đi một đoạn). Để bản v2 nếu cần.

## 2. Các file sẽ được tạo (thư mục `data/eta/`)

| File | Nội dung |
|---|---|
| `eta_trips.csv` | Bảng chính: mỗi dòng một chuyến (xem mục 3) |
| `eta_schema.json` | Danh sách đặc trưng **theo đúng thứ tự**, kiểu dữ liệu, giá trị hạng mục hợp lệ, tham số chuẩn hoá (nếu có) — hợp đồng đầu vào giữa Kaggle và backend |
| `eta_generator_params.json` | Mọi tham số của bộ sinh (tốc độ theo khung giờ, hệ số mưa, xác suất sự cố, độ trôi…) để tái lập và để bạn biết mô hình *đáng ra* học được gì |
| `ETA_TRAINING_GUIDE.md` | Hướng dẫn ngắn + mã mẫu: đọc CSV, huấn luyện P50/P90, đánh giá, **xuất ONNX** |

## 3. Cột của `eta_trips.csv`

Ba nhóm cột: **định danh/chia tập**, **đặc trưng (được dùng để dự báo)**, **nhãn + cột chỉ để phân tích**.

### 3.1 Định danh và chia tập
| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `trip_id` | int | Số thứ tự chuyến, tăng theo thời gian |
| `depart_at` | ISO 8601 có múi giờ `+07:00` | Giờ xe rời điểm lấy hàng (giờ vận hành) |
| `split` | `train` \| `calib` \| `test` | Chia **theo thời gian** (mục 5). **Không** phải đặc trưng |

### 3.2 Đặc trưng — CHỈ những gì biết được lúc xuất phát (thứ tự này là thứ tự đầu vào của mô hình)
| # | Cột | Kiểu | Giá trị / khoảng | Ghi chú |
|---|---|---|---|---|
| 1 | `distance_km` | float | 8 – 40 | Quãng đường điểm lấy → ICD. **Phải phủ cả quãng thực app sẽ đưa vào** (tuyến OSRM/nội suy của hành lang seed khoảng 10–20 km) — xem câu hỏi 7 |
| 2 | `hour` | int | 0 – 23 | Giờ địa phương lúc xuất phát |
| 3 | `weekday` | int | 0 – 6 | 0 = thứ Hai |
| 4 | `is_weekend` | int | 0/1 | = `weekday >= 5` |
| 5 | `month` | int | 1 – 12 | Để mô hình thấy xu hướng theo mùa |
| 6 | `rain_mm_h` | float | 0 – 30 | Lượng mưa tại thời điểm xuất phát (mô phỏng) |
| 7 | `wind_kmh` | float | 0 – 60 | Gió (mô phỏng) |
| 8 | `route_id` | hạng mục | `KCN_A_ICD`, `KCN_B_ICD` | 2 tuyến = 2 điểm lấy hàng trong seed (KCN Sóng Thần, KCN VSIP I) → ICD. Depot chỉ là nơi xe đứng, **không** phải điểm lấy hàng nên không có tuyến `DEPOT_ICD`. One-hot theo đúng thứ tự trong `eta_schema.json` |
| 9 | `vehicle_class` | hạng mục | `heavy` (24 tấn), `medium` (18 tấn), `light` (8 tấn) | Xe nặng chậm hơn một chút. Backend suy ra từ `capacity_kg` của xe (24.000 / 18.000 / 8.000 trong seed) |

Cột phái sinh (có sẵn trong CSV để tiện, tính từ đặc trưng, **không** thêm thông tin): `band` ∈ {`night`, `normal`, `peak_am`, `peak_pm`} — cùng định nghĩa khung giờ với `app/eta/baseline.py` (peak_am 7–8h, peak_pm 16–18h, night 22–5h).

### 3.3 Nhãn
| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `actual_transit_min` | float | **Nhãn**: thời gian trung chuyển thực tế (phút) |

### 3.4 Baseline (tính **chỉ từ đặc trưng**, để bạn so sánh công bằng)
| Cột | Ý nghĩa |
|---|---|
| `rule_const_min` | Luật hiện tại của hệ thống: hằng số **90** phút (baseline yếu) |
| `rule_dist_min` | Luật **theo quãng đường và khung giờ**: `distance_km ÷ tốc độ trung bình của khung giờ` — baseline **mạnh hơn**, là đối thủ chính của mô hình |
| `baseline_median_min` | **Median theo (tuyến, khung giờ)** tính **chỉ trên tập `train`** — đúng baseline DRAFT 6.2 yêu cầu so sánh (không rò rỉ: median được tính từ train rồi gắn vào mọi dòng) |
| `rule_dist_p90_min` | P90 của luật trên theo hệ số nới của khung giờ (giống ý tưởng `baseline.p90_extra_minutes`) |

### 3.5 Cột CHỈ để phân tích — **TUYỆT ĐỐI KHÔNG đưa vào đặc trưng** (rò rỉ hoặc không biết trước)
| Cột | Ý nghĩa |
|---|---|
| `gate_queue_min` | Thời gian chờ ở cổng ICD (một phần của nhãn; lúc xuất phát chưa biết) |
| `had_incident` | 0/1: có sự cố dọc đường (hỏng xe, tai nạn) |
| `incident_delay_min` | Số phút trễ do sự cố |
| `scenario_tag` | `normal` \| `drift` \| `incident` — để chia nhỏ khi đánh giá |

## 4. Cách bộ sinh tạo nhãn (để bạn biết mô hình *đáng ra* học được gì)

```
tốc_độ_hiệu_dụng(band): night 26 · normal 19.5 · peak_am 13.5 · peak_pm 12.5   (km/h, ĐÃ GỒM dừng đèn đỏ, xếp hàng, thao tác)
hệ_số_xe          : heavy 1.12 · medium 1.00 · light 0.93            (thời gian nhân hệ số)
hệ_số_tuyến       : KCN_A 1.00 · KCN_B 1.06
hệ_số_cuối_tuần   : 0.93
hệ_số_mưa         : 1 + 0.018 × rain_mm_h (tối đa 1.35);  gió ≥ 50 km/h: +0.04
xu_hướng_tháng    : tháng 10–12 chậm hơn ~6% (mùa hàng cuối năm), tháng 2 nhanh hơn ~5%

thời_gian_chạy = distance_km ÷ tốc_độ_hiệu_dụng × 60 × hệ_số_xe × hệ_số_tuyến × hệ_số_cuối_tuần × hệ_số_mưa × xu_hướng_tháng
nhiễu          = nhân với lognormal(0, σ) · σ = 0.08 (night) … 0.16 (peak)   → lệch phải (trễ nhiều hơn sớm)
chờ_cổng       = Exponential(trung bình 6 phút; 14 phút ở peak_pm)           → cộng thêm
sự_cố          = xác suất 2.5% mỗi chuyến, cộng thêm Uniform(20, 90) phút     → đuôi dài
actual_transit_min = thời_gian_chạy × nhiễu + chờ_cổng + sự_cố
```

**Kiểm tra số học (để bạn tự tính lại):** ở `distance_km = 26`, khung `normal`, xe `medium`, tuyến A, ngày thường, trời khô: `26 ÷ 19,5 × 60 = 80` phút, cộng chờ cổng trung bình 6 → **≈ 86 phút** cho xe `medium`, tuyến A, trời khô; trung vị của **cả nhóm** quãng 25–27 km giờ thường (gồm xe nặng, tuyến B, mưa, mùa cuối năm) đo được khoảng **90 phút**, khớp giả định hiện tại của hệ thống (`transit_minutes = 90`). Lưu ý: tốc độ hiệu dụng ~19,5 km/h là **thấp** (để khớp giả định 90 phút cho 26 km của hệ thống hiện tại), không phản ánh xe tải thật.

Hiệu chỉnh để trung vị ở `distance_km ≈ 26`, khung `normal` ≈ **90 phút** — khớp giả định hiện tại của hệ thống (`transit_minutes = 90`), nên mô hình thay thế được ETA hiện tại mà không lệch mặt bằng.

**Độ trôi (drift) có chủ ý:** trong **2 tháng cuối** (đoạn `test`), giao thông chậm hơn **+8%** và xác suất sự cố tăng lên 4% (ví dụ công trình mới). Mục đích: kiểm tra cổng phát hiện trôi — mô hình huấn luyện ở giai đoạn cũ phải bị phát hiện/hạ về luật khi độ phủ P90 tụt.

## 5. Quy mô và cách chia tập

- **Giai đoạn:** 12 tháng liên tục, `2025-11-01` → `2026-10-31` (giờ VN).
- **Số chuyến:** khoảng **20.000** (≈ 55 chuyến/ngày, nhiều hơn vào giờ làm việc, ít vào ban đêm).
- **Chia THEO THỜI GIAN (không xáo trộn):**

| split | Khoảng thời gian | Số chuyến (xấp xỉ) | Dùng để |
|---|---|---|---|
| `train` | 2025-11-01 → 2026-06-30 (8 tháng) | ~13.500 | Huấn luyện |
| `calib` | 2026-07-01 → 2026-08-31 (2 tháng) | ~3.300 | Hiệu chỉnh P90 (và chọn siêu tham số) |
| `test` | 2026-09-01 → 2026-10-31 (2 tháng, **có drift**) | ~3.300 | Đánh giá cuối, **không đụng tới khi huấn luyện** |

- Hạt giống cố định `20261111` → sinh lại ra đúng file này.
- Không có giá trị thiếu (NaN) trong đặc trưng; nhãn luôn có.

## 6. Yêu cầu đối với mô hình (để cắm vào backend được)

1. **Đầu vào:** ma trận `float32` kích thước `[N, F]`, cột đúng thứ tự trong `eta_schema.json` (hạng mục đã one-hot theo thứ tự đó; số đã chuẩn hoá nếu bạn chuẩn hoá — **nhúng bước chuẩn hoá vào chính model ONNX** để backend không phải lặp lại).
2. **Đầu ra:** `float32 [N, 2]` = (`p50_minutes`, `p90_minutes`), bảo đảm `p90 ≥ p50` (ví dụ `p90 = p50 + softplus(...)`).
3. **Hàm mất mát gợi ý:** *pinball loss* (quantile loss) tại 0.5 và 0.9; sau đó **hiệu chỉnh P90 trên tập `calib`** (cộng độ lệch phân vị 0.9 của phần dư), như `ml.py` đang làm.
4. **Xuất file:** `eta_model.onnx` (opset ≥ 17) + `eta_model_card.json` (mục 8). Có thể huấn luyện bằng PyTorch rồi `torch.onnx.export` (server **không** cài PyTorch).
5. **Không** dùng cột ở mục 3.5 và cột `split`, `trip_id`, `depart_at` làm đặc trưng.

## 7. Cách đánh giá (trên `test`, và chia nhỏ theo `band`, `route_id`, `scenario_tag`)

| Chỉ số | Cách tính |
|---|---|
| MAE P50 (phút) | `mean(|p50 − actual|)` |
| Pinball loss @0.5 và @0.9 | Chuẩn |
| **Độ phủ P90** | `mean(actual ≤ p90)` — mục tiêu 0,85 – 0,97 |
| Tỷ lệ trong ±15 phút | `mean(|p50 − actual| ≤ 15)` |
| **P90 của sai số tuyệt đối** | `quantile(|p50 − actual|, 0.9)` (DRAFT 6.2 yêu cầu báo riêng) |
| So baseline | Cải thiện MAE so với `baseline_median_min` (**DRAFT 6.2**), `rule_dist_min` (mạnh) **và** `rule_const_min` (yếu) |

**Cổng promote của hệ thống (giữ nguyên như `ml.py`):** dùng mô hình thay luật **chỉ khi** MAE giảm **≥ 15%** so với luật **và** độ phủ P90 nằm trong **[0,85; 0,97]**; ngược lại tự hạ về luật. Khuyến nghị tính cổng so với baseline **mạnh nhất** trong ba cái (thường `baseline_median_min` hoặc `rule_dist_min`), vì thắng `rule_const_min` (hằng số 90) là quá dễ. DRAFT 6.2 còn yêu cầu mô hình **không làm xấu quyết định vận hành**: vì hard gate **không** dùng ML (chỉ ETA luật P50), điều kiện này được giữ bằng thiết kế — ML chỉ là thông tin tham khảo và cảnh báo mềm.

## 8. `eta_model_card.json` bạn đính kèm khi gửi model về

```json
{
  "model_version": "eta-onnx-sim-v1",
  "model_file": "eta_model.onnx",
  "sha256": "<mã băm của file .onnx>",
  "trained_on": "eta_trips.csv (sha256: ...)",
  "framework": "pytorch x.y -> onnx opset 17",
  "feature_order": ["distance_km", "hour", "..."],
  "metrics_test": {"mae_p50": 0, "p90_coverage": 0, "within15": 0, "improvement_vs_rule_dist_pct": 0, "improvement_vs_rule_const_pct": 0},
  "notes": "huấn luyện trên dữ liệu MÔ PHỎNG"
}
```

## 8b. Ràng buộc của dự án khi tích hợp (đối chiếu `CLAUDE.md` / `DRAFT.md`)

- **Đổi stack phải ghi lý do (CLAUDE.md mục 3 + 11):** bản hiện tại dùng scikit-learn; thêm `onnxruntime` để nạp model từ Kaggle là **thay đổi stack** → phải ghi vào mục 10 (changelog) *trước khi* áp dụng: đổi để giải quyết gì (dùng model huấn luyện ngoài mà không cài PyTorch lên Render 512 MB), đánh đổi gì (thêm một phụ thuộc, thêm bước kiểm mã băm).
- **Mọi đặc trưng phải tồn tại lúc dự báo (DRAFT 6.2):** `rain_mm_h` và `wind_kmh` ở app chỉ có khi tín hiệu thời tiết bật và gọi được. **Thiếu thời tiết → không đoán**: dùng giá trị 0 và hạ độ tin cậy, hoặc hạ hẳn về ETA luật (sẽ chốt khi tích hợp); không được bịa số.
- **Hạ về luật (CLAUDE.md mục 7):** thiếu file model, mã băm sai, lỗi nạp/chạy, độ phủ P90 tụt hoặc đầu vào ngoài phạm vi huấn luyện (ví dụ `distance_km` ngoài 8–40) → dùng ETA luật, hiển thị độ tin cậy thấp.
- **Nhãn trung thực (CLAUDE.md mục 7):** giao diện ghi "lịch sử mô phỏng — chưa chứng minh độ chính xác thật"; không trình bày như ML đã huấn luyện trên chuyến thật. Ghi `model_version` + mã băm lúc dự báo (DRAFT 6.2: lưu features/model/version).
- **Hard gate giữ nguyên:** vẫn dùng P50 của ETA luật; ML không đổi quyết định ghép (CLAUDE.md mục 1 và 6).

## 9. Những điều bộ dữ liệu này KHÔNG chứng minh (sẽ ghi trên giao diện)

- Không chứng minh dự báo đúng với xe thật: mô hình chỉ học lại công thức ở mục 4.
- Không có GPS thật, giao thông thật, thời tiết thật; mưa/gió là chuỗi mô phỏng.
- Con số "giảm X% sai số" phụ thuộc cách sinh dữ liệu — khi trình bày, nhấn vào **cơ chế** (chia theo thời gian, cổng promote, tự hạ về luật khi trôi), không phải con số.

## 10. Câu hỏi cần bạn chốt trước khi tôi sinh dữ liệu

1. **Quy mô:** 20.000 chuyến / 12 tháng có hợp lý không (hay muốn nhỏ hơn cho Kaggle chạy nhanh, ví dụ 8.000)?
2. **Drift ở cuối (mục 4)** có muốn giữ không? Nếu có, mức +8% / sự cố 4% có ổn không? (Nhớ: cổng độ phủ hiện rất chặt, drift lớn thì mô hình bị hạ về luật.)
3. **Tuyến và xe:** 2 tuyến (khớp seed) và 3 hạng xe có đủ không, hay bỏ `vehicle_class` cho đơn giản?
4. **Baseline `rule_dist_min`:** đồng ý dùng làm đối thủ chính? (Việc cho ETA luật của hệ thống *thật sự* tính theo quãng đường là việc tách riêng, đổi kết quả ghép, cần bạn duyệt sau.)
5. **Dự báo giữa đường (v2):** có cần thêm không, hay chỉ dự báo lúc xuất phát là đủ cho demo?
6. **Mưa/gió:** giữ dạng số liên tục (`rain_mm_h`, `wind_kmh`) hay chỉ cờ mưa 0/1 cho khớp `ml.py` hiện tại? (Số liên tục khớp với Open-Meteo hơn, nhưng thiếu dữ liệu thì phải hạ về luật.)
7. **Quãng đường:** hành lang seed chỉ ~10–20 km nhưng giả định hiện tại là 90 phút cho ~26 km. Giữ 26 km làm trung tâm (khớp giả định cũ) hay sinh quanh 10–20 km (khớp hành lang thật của app, nhưng khi đó tốc độ hiệu dụng phải đổi và trung vị sẽ không còn ~90 phút)?
