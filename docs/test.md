# Hướng dẫn test tính năng ETA có model đã huấn luyện (ONNX)

> ⚠️ Model được huấn luyện trên **dữ liệu MÔ PHỎNG** — các số bên dưới chỉ để kiểm tra **đúng quy trình** (nạp model, cổng promote, tự hạ về luật, ngữ cảnh chuyến), **không** nói lên độ chính xác ngoài đời.
> Các "kết quả mong đợi" là số đo thật khi viết tài liệu (12/11/2026) với model `eta-onnx-sim-v1` không drift. Model là hàm xác định nên **cùng model ⇒ cùng số** (trừ các ca phụ thuộc thời tiết thật).

## 0. Bức tranh tổng thể (đọc 1 phút)

| Thứ | Vai trò | Có đổi quyết định ghép không? |
|---|---|---|
| **ETA luật** (hằng số 25′ + 90′, P90 nới theo khung giờ) | ETA chính thức trong đề xuất; **hard gate dùng P50 này** | **Có** (đây là thứ duy nhất quyết định) |
| **ETA trực tiếp** (từ vệt GPS mô phỏng) | Hiển thị cho chuyến đang chạy | Không (cảnh báo mềm) |
| **ETA tín hiệu thật** (OSRM đường bộ + thời tiết + kẹt xe Mapbox nếu có khoá) | Hiển thị bên cạnh | Không |
| **ETA ML — model ONNX** (file `backend/model/eta_model.onnx`) | Thông tin tham khảo, chip **"ML a–b phút"** ở màn Theo dõi | **Không** (mã `matching/` và `booking/` không dùng ML) |

Model chỉ được dùng khi: (1) mã băm file khớp `eta_model_card.json`, (2) thứ tự đặc trưng khớp hợp đồng, (3) **qua cổng promote** (giảm MAE ≥ 15% so với baseline mạnh nhất **và** độ phủ P90 ∈ [0,85; 0,97]). Sai một điều ⇒ **tự hạ về ETA luật**.

## 1. Chuẩn bị

```bash
# Terminal 1 — backend (cổng 8001 để không đụng tiến trình khác); cần Docker DB đang chạy: docker compose up -d
cd backend && PGHOSTADDR=127.0.0.1 .venv/bin/uvicorn app.main:app --port 8001

# Terminal 2 — frontend trỏ vào backend đó
cd frontend && VITE_API_URL=http://127.0.0.1:8001 npm run dev      # http://127.0.0.1:5173

# Terminal 3 — dùng cho các lệnh curl bên dưới
export API=http://127.0.0.1:8001
```

Token dev (không mật khẩu): `dev:shipper_a` (Nguyên, chủ hàng) · `dev:carrier_b` (Minh, vận tải) · `dev:node_c` (Khôi, ICD) · `dev:dispatch` (Phú, điều phối viên).
Nếu server có đặt `PIVOT_ADMIN_KEY`, các endpoint `/v1/eta/sandbox/*` cần thêm header `-H "X-Admin-Key: <mã>"` (chạy local thường không có).

---

## Kịch bản 1 — Chạy bộ test tự động (2 phút)

```bash
cd backend
PGHOSTADDR=127.0.0.1 .venv/bin/python -m pytest tests/test_eta_onnx.py tests/test_eta_data_gen.py tests/test_eta_sandbox.py tests/test_eta.py tests/test_eta_signals.py -q
```
**Mong đợi:** `76 passed`. Toàn bộ test: `pytest` → **328 passed**.
Test quan trọng nhất là `test_backend_reproduces_the_metrics_in_the_model_card_on_the_test_split`: chạy lại model bằng **code backend** trên tập test của `data/eta_nodrift/eta_trips.csv` phải ra đúng **MAE 14,31′ và độ phủ P90 0,878** như trong model card ⇒ cách backend ghép đặc trưng khớp với notebook.

## Kịch bản 2 — Model đã nạp và đang được dùng

```bash
curl -s -H "Authorization: Bearer dev:shipper_a" $API/v1/eta/model | python3 -m json.tool | head -40
```
**Mong đợi (các trường chính):**

| Trường | Giá trị |
|---|---|
| `source` | `"onnx"` |
| `label` | `"eta-onnx-sim-v1"` |
| `status` / `reason` | `"promoted"` / `"ok"` |
| `forced` | `false` |
| `baseline` | `"baseline_median_min"` |
| `metrics.mae_rule` → `mae_ml` | `22.38` → `14.31` |
| `metrics.improvement_pct` | `36.08` (cần ≥ 15) |
| `metrics.p90_coverage_ml` | `0.878` (cần 0,85 – 0,97) |
| `is_simulated_history` | `true` (và `note` có chữ "MÔ PHỎNG") |

**Trên giao diện:** đăng nhập **Phú (Điều phối viên)** → tab **Theo dõi** → cuối trang mở mục **"Mô hình ETA"**. Phải thấy:
- chip **"ML đang dùng"**, chip **`eta-onnx-sim-v1`** (rê chuột ra mã băm sha256), chip **MÔ PHỎNG**;
- bảng `Luật | ML`: **MAE 22.3833′ | 14.3082′**, **±15′ 46% | 67%**, **P90 85% | 88%** (cột "Luật" ở đây là baseline mạnh nhất — median theo tuyến/khung giờ);
- dòng "Giảm MAE 36.08% (cần ≥ 15%). So baseline_median_min.";
- **không có** nút "Huấn luyện lại" (model ONNX huấn luyện ngoài, không huấn luyện trong app).

## Kịch bản 3 — What-if: ETA đổi theo giờ xuất phát

Cùng một chuyến 26 km, xe cỡ trung, tuyến A, chỉ đổi giờ:

```bash
for H in 02 08 10 17; do
  echo -n "$H giờ: "
  curl -s -X POST $API/v1/eta/predict -H "Authorization: Bearer dev:carrier_b" -H "Content-Type: application/json" \
   -d "{\"depart_at\":\"2026-11-12T${H}:00:00+07:00\",\"km\":26,\"route_id\":\"KCN_A_ICD\",\"vehicle_class\":\"medium\"}" \
   | python3 -c "import sys,json; d=json.load(sys.stdin); m=d['ml']; print('luật P50 =',d['rule']['minutes_p50'],'| ML P50–P90 =',m['p50_minutes'],'–',m['p90_minutes'],'| dùng:',d['used'])"
done
```
**Mong đợi:**

| Giờ đi | Khung | Luật P50 | ML P50–P90 |
|---|---|---|---|
| 02:00 | đêm | 90 | **66 – 81** |
| 08:00 | cao điểm sáng | 90 | **117 – 147** |
| 10:00 | thường | 90 | **85 – 104** |
| 17:00 | cao điểm chiều | 90 | **149 – 189** |

✔ Đạt khi: thứ tự **17h > 08h > 10h > 02h**, luật luôn 90′ (không đổi theo giờ — đúng thiết kế, hard gate ổn định), `used = "ml"`, và **P90 ≥ P50** ở mọi dòng.

## Kịch bản 4 — What-if: quãng đường, hạng xe, mưa

Thêm tham số tuỳ chọn vào body (`km`, `route_id`, `vehicle_class`, `rain_mm_h`, `wind_kmh`). Giờ cố định 10:00:

| Đổi gì | Body thêm | ML P50–P90 mong đợi |
|---|---|---|
| Gốc (26 km, medium, khô) | — | 85 – 104 |
| Gần hơn | `"km":15` | **55 – 72** |
| Xa hơn | `"km":35` | **119 – 139** |
| Xe nặng | `"vehicle_class":"heavy"` | **99 – 118** |
| Xe nhẹ | `"vehicle_class":"light"` | 86 – 110 |
| Mưa to | `"rain_mm_h":20` | **155 – 194** |

✔ Đạt khi: xa hơn ⇒ lâu hơn, xe nặng ≥ xe trung, mưa ⇒ lâu hơn.
📝 **Ghi nhận khi test (điểm yếu của model, không phải lỗi hệ thống):** (a) xe nhẹ ≈ xe trung (model chưa phân biệt rõ); (b) mưa 20 mm/h tăng ETA nhiều hơn công thức sinh dữ liệu (trần hệ số 1,35 ⇒ ~115′) — mưa lớn hiếm trong dữ liệu huấn luyện nên model ngoại suy mạnh. Đây là ví dụ để nói rõ "chỉ chứng minh quy trình".
Nếu **không** truyền `route_id`/`vehicle_class`/mưa/gió, kết quả `ml.assumed` liệt kê các giá trị đã giả định (tuyến A, xe medium, trời khô) và `confidence` ghi "assumed …".

## Kịch bản 5 — Đầu vào lạ: hạ về luật, không bịa

```bash
# 5 km và 60 km nằm NGOÀI phạm vi huấn luyện (8–40 km) → không ngoại suy
curl -s -X POST $API/v1/eta/predict -H "Authorization: Bearer dev:carrier_b" -H "Content-Type: application/json" \
  -d '{"depart_at":"2026-11-12T10:00:00+07:00","km":5}'   | python3 -c "import sys,json; d=json.load(sys.stdin); print('used=',d['used'],'| ml=',d['ml'])"
# giá trị sai kiểu → 422
curl -s -o /dev/null -w "route_id lạ: HTTP %{http_code}\n" -X POST $API/v1/eta/predict -H "Authorization: Bearer dev:carrier_b" -H "Content-Type: application/json" -d '{"depart_at":"2026-11-12T10:00:00+07:00","route_id":"X"}'
curl -s -o /dev/null -w "mưa 99 mm/h:   HTTP %{http_code}\n" -X POST $API/v1/eta/predict -H "Authorization: Bearer dev:carrier_b" -H "Content-Type: application/json" -d '{"depart_at":"2026-11-12T10:00:00+07:00","rain_mm_h":99}'
```
**Mong đợi:** `km=5` và `km=60` ⇒ `used = rule`, `ml = None` (luật P50 lần lượt 17′ và 208′); hai lệnh sau ⇒ **HTTP 422**.

## Kịch bản 6 — Chuyến thật: ML dùng đúng tuyến, xe, quãng đường

> ⚠️ Script bên dưới **reset dữ liệu mô phỏng** của DB đang dùng (xoá đề xuất/sự kiện, giữ danh tính). Chỉ chạy trên DB dev.

```bash
python3 - <<'EOF'
import json, uuid, urllib.request, os
B = os.environ.get("API", "http://127.0.0.1:8001")
def call(user, path, method="GET", body=None, idem=False):
    h = {"Authorization": f"Bearer dev:{user}", "Content-Type": "application/json"}
    if idem: h["Idempotency-Key"] = str(uuid.uuid4())
    r = urllib.request.Request(B + path, method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
    return json.load(urllib.request.urlopen(r))
call("dispatch", "/v1/demo/reset?provision=false", "POST")
lot = next(s for s in call("shipper_a", "/v1/shipments") if s["code"] == "LOT-A-001")
prop = call("shipper_a", "/v1/match-runs", "POST", {"shipment_id": lot["id"]})["proposals"][0]; pid = prop["id"]
call("shipper_a", f"/v1/proposals/{pid}/hold", "POST", {"version": prop["version"]}, True)
for who in ("carrier_b", "shipper_a", "node_c"):
    call(who, f"/v1/proposals/{pid}/accept", "POST", {"version": call(who, f"/v1/proposals/{pid}")["version"]}, True)
t = call("shipper_a", f"/v1/tracking/{pid}")
print("trạng thái:", call("shipper_a", f"/v1/proposals/{pid}")["status"], "| quãng điểm lấy→ICD:", t["total_km"], "km")
print("ETA ML:", t["eta_ml"])
EOF
```
**Mong đợi:** `trạng thái: confirmed`; `eta_ml` có `"method": "ml-onnx"`, `p50_minutes ≈ 36`, `p90_minutes ≈ 50` (quãng ~8,7 km), `"forced": false`. Trường `assumed` **rỗng** nếu máy có Internet (thời tiết lấy từ Open-Meteo); nếu không gọi được thời tiết, `assumed = ["rain_mm_h","wind_kmh"]` và `confidence` ghi rõ "assumed" (giả định trời khô — không đoán lặng lẽ).

**Làm bằng giao diện:** thêm **Nguyên, Minh, Khôi** (nút **+** → "Mở cả chuỗi ba bên") → Nguyên: **Ghép** lô `LOT-A-001` → **Giữ chỗ** → Nguyên/Minh/Khôi bấm **Xác nhận** → mở **Theo dõi** (cửa sổ bất kỳ). Khối **"ETA tới ICD"** có dòng chip **`Luật`** và **`ML 36–50 phút`**.

📝 **Cần hiểu để không hoảng:** ETA ML (~36–50′) **thấp hơn nhiều** ETA luật (hằng số 90′). Lý do: hành lang seed chỉ ~8,7 km, còn luật được hiệu chỉnh cho ~26 km. ML thể hiện đúng quãng thật của chuyến — đây là điểm cho thấy ETA luật hằng số chưa theo quãng đường (đã ghi trong CLAUDE.md, chưa sửa vì sẽ đổi kết quả ghép).
Chuyến có điểm lấy hàng không nhận ra (ví dụ gán điểm lấy là Depot) hoặc quãng < 8 km ⇒ **không có chip ML** (hạ về luật) — đúng thiết kế.

## Kịch bản 7 — Cổng promote: model có drift KHÔNG được dùng

`backend/model/archive_drift/` là model bạn train trên Kaggle với dữ liệu có drift (độ phủ P90 0,765 ⇒ **không qua cổng**).
Chạy một server tạm ở cổng 8011:

```bash
cd backend
# 7a) trỏ vào model có drift, KHÔNG ép
PGHOSTADDR=127.0.0.1 PIVOT_ETA_MODEL_DIR=$PWD/model/archive_drift .venv/bin/uvicorn app.main:app --port 8011
#   (terminal khác)
curl -s -H "Authorization: Bearer dev:shipper_a" http://127.0.0.1:8011/v1/eta/model | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['reason'])"
```
**Mong đợi 7a:** `rule_fallback p90_coverage_out_of_range`; `/v1/eta/predict` ⇒ `used = rule`, `ml = null`; chuyến ở Theo dõi **không có chip ML**.

```bash
# 7b) ép dùng thử (chỉ để demo/thử): thêm PIVOT_ETA_MODEL_FORCE=true
PGHOSTADDR=127.0.0.1 PIVOT_ETA_MODEL_DIR=$PWD/model/archive_drift PIVOT_ETA_MODEL_FORCE=true .venv/bin/uvicorn app.main:app --port 8011
```
**Mong đợi 7b:** `status = forced`, `reason = gate_forced`, `note` có "Cổng promote KHÔNG đạt; đang bật thủ công"; dự báo 8h sáng **118 – 149**, `confidence` chứa **"promotion gate NOT passed (manual override)"**. Giao diện hiện chip **"ML bật thủ công"** (màu cảnh báo).
✔ Đạt khi: ép vẫn bị gắn nhãn cảnh báo ở **mọi** chỗ, không bao giờ trông như model đã qua cổng.

## Kịch bản 8 — Model bị sửa/hỏng ⇒ không dùng

```bash
cd backend && mkdir -p /tmp/eta_bad && cp model/eta_model.onnx model/eta_model_card.json /tmp/eta_bad/ && printf 'x' >> /tmp/eta_bad/eta_model.onnx
PGHOSTADDR=127.0.0.1 PIVOT_ETA_MODEL_DIR=/tmp/eta_bad PIVOT_ETA_MODEL_FORCE=true .venv/bin/uvicorn app.main:app --port 8011
```
**Mong đợi:** `status = rule_fallback`, `reason = sha_mismatch` (**kể cả khi FORCE=true**), `predict ⇒ used = rule`. Giao diện thẻ "Mô hình ETA" hiện "Model lỗi, dùng luật." Các lỗi tương tự (đã có test): `feature_order_mismatch`, `card_invalid`, `model_file_missing`, `model_load_error`.
✔ Đạt khi: model hỏng **không** làm app sập, **không** lặng lẽ dùng model khác.

## Kịch bản 9 — Tắt model ONNX

> Khi model ONNX đang là nguồn chính thức, `POST /v1/eta/train` trả **409 `ONNX_MODEL_IN_USE`** (huấn luyện lại trong app chỉ đụng mô hình mô phỏng không dùng). Kịch bản demo số 10 (`eta_model`) tự nhận biết nguồn: nhánh ONNX kiểm "train bị từ chối 409" + "quét độ trôi hạ về luật mà không đổi model đang dùng"; nhánh mô phỏng giữ luồng huấn luyện cũ.

```bash
PGHOSTADDR=127.0.0.1 PIVOT_ETA_MODEL_DIR= .venv/bin/uvicorn app.main:app --port 8011      # đặt RỖNG = tắt
```
**Mong đợi:** `/v1/eta/model` ⇒ `source = "sim"`, `label = "ml-sim-v1"` (mô hình scikit-learn mô phỏng cũ, huấn luyện lại lúc khởi động); thẻ "Mô hình ETA" **có lại** nút "Huấn luyện lại"/"Thử với dữ liệu trôi". Dự báo 8h sáng ≈ **115 – 122**.

## Kịch bản 10 — ETA Sandbox (công cụ nội bộ)

```bash
cd backend
.venv/bin/python -m app.eta_sandbox_cli --only scenarios      # không cần server/DB
.venv/bin/python -m app.eta_sandbox_cli --only drift
.venv/bin/python -m app.eta_sandbox_cli --only signals        # gọi mạng thật; thêm --fresh để bỏ qua cache
```
**Mong đợi:**
- **scenarios** (đi qua model ONNX, mặc định tuyến A, xe medium, 26 km, trời khô): peak_am **117/146**, peak_pm **146/187**, night **64/77**, normal **84/104** (ML P50/P90), cột "đang dùng" = `ml`.
- **drift** (⚠️ chạy trên **pipeline scikit-learn mô phỏng**, không phải ONNX): drift 0 ⇒ DÙNG ML; từ **0,05** trở lên ⇒ "hạ về luật" (độ phủ P90 tụt 0,88 → 0,68…).
- **signals**: bảng 3 nguồn `osrm`, `weather`, `mapbox` với trạng thái `ok | error | disabled | not_configured`. `mapbox = not_configured` là bình thường khi chưa có `PIVOT_MAPBOX_TOKEN`. `error` ở `weather` thường là do mạng chậm (timeout 2,5 giây) — chạy lại.

Qua API (vai Phú): `curl -H "Authorization: Bearer dev:dispatch" $API/v1/eta/sandbox/drift-sweep` (và `/scenarios`, `/signals-health?fresh=true`). Vai khác ⇒ **403**.

## Kịch bản 11 — ML không đổi quyết định ghép (hard gate)

1. Chạy **Ghép** lô `LOT-A-001` khi model đang `promoted` (mặc định). Ghi lại danh sách xe đề xuất + điểm + P50 trong chi tiết đề xuất.
2. Khởi động lại server với `PIVOT_ETA_MODEL_DIR=` (tắt model) rồi reset dữ liệu và **Ghép** lại đúng lô đó.

**Mong đợi:** **cùng xe, cùng thứ hạng, cùng ETA luật P50** (điểm có thể lệch rất nhỏ vì mốc "bây giờ" khác nhau giữa hai lần chạy) — vì `matching/` và `booking/` không dùng ML. Kiểm tra bằng mã: lệnh sau phải **không in ra dòng nào**:
```bash
grep -rnE "onnx_model|import ml\b|eta import .*\bml\b|\bml\.(predict|model_info|train)" backend/app/matching backend/app/booking
```

## Kịch bản 12 — Tái huấn luyện và thay model (khi muốn model mới)

```bash
cd backend
.venv/bin/python -m app.eta_data_gen --out ../data/eta_nodrift --no-drift   # sinh dữ liệu (thêm/bớt --no-drift tuỳ ý)
```
1. Upload `eta_trips.csv` + `eta_schema.json` lên Kaggle, import `data/eta/eta_train_kaggle.ipynb`, **Run All** (hướng dẫn: `data/eta/ETA_TRAINING_GUIDE.md`). Cuối notebook in dòng **"CỔNG PROMOTE: … ĐƯỢC DÙNG / HẠ VỀ ETA LUẬT"**.
2. Tải `eta_model.onnx` + `eta_model_card.json` về, **chép đè** vào `backend/model/` (giữ bản cũ nếu cần).
3. Kiểm tra mã băm khớp:
   ```bash
   shasum -a 256 backend/model/eta_model.onnx            # phải bằng "sha256" trong eta_model_card.json
   ```
4. Restart backend ⇒ làm lại **Kịch bản 2** (status/reason) và **Kịch bản 1** (pytest).
Lưu ý: test "ánh xạ đặc trưng" so với `data/eta_nodrift/eta_trips.csv`; nếu bạn huấn luyện trên dữ liệu khác, test này sẽ lệch và cần trỏ lại CSV đúng.

---

## Bảng lỗi thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `status = rule_fallback`, `reason = p90_coverage_out_of_range` | Model không qua cổng (vd. bản có drift) | Dùng bản `--no-drift`, hoặc `PIVOT_ETA_MODEL_FORCE=true` **chỉ để thử** |
| `reason = sha_mismatch` | File `.onnx` khác `sha256` trong card (chép thiếu/sửa file) | Chép lại **cả hai** file từ cùng một lần huấn luyện |
| `reason = feature_order_mismatch` | Model xuất với thứ tự đặc trưng khác | Huấn luyện lại bằng notebook mẫu (hợp đồng 12 đặc trưng) |
| `reason = runtime_missing` | Thiếu `onnxruntime` trong venv | `cd backend && .venv/bin/pip install -r requirements.txt` |
| Chuyến thật không có chip "ML" | Chưa `confirmed/executing`; hoặc điểm lấy hàng/quãng ngoài phạm vi (8–40 km); hoặc model đang `rule_fallback` | Xem Kịch bản 2 và 6 |
| `/v1/eta/model` ra `source = sim` | `PIVOT_ETA_MODEL_DIR` rỗng hoặc thư mục không có file model | Bỏ biến đó để dùng `backend/model/` mặc định |
| `weather: error` trong signals | Open-Meteo chậm/không có mạng (timeout 2,5 giây) | Chạy lại; hoặc `PIVOT_SIGNALS_ENABLED=false` để tắt — ML vẫn chạy với giả định trời khô |

## Checklist nghiệm thu nhanh

- [ ] K1 — `76 passed` (nhóm ETA), toàn bộ `328 passed`
- [ ] K2 — `promoted / ok`, MAE 22,38′ → 14,31′, độ phủ P90 0,878, nhãn MÔ PHỎNG
- [ ] K3 — ETA ML theo giờ: 17h > 08h > 10h > 02h; luật luôn 90′
- [ ] K4 — xa hơn ⇒ lâu hơn; xe nặng ≥ xe trung; mưa ⇒ lâu hơn; (ghi nhận điểm yếu mưa to)
- [ ] K5 — ngoài 8–40 km ⇒ dùng luật; đầu vào sai ⇒ 422
- [ ] K6 — chuyến thật có chip "ML 36–50 phút"; chuyến không nhận ra tuyến ⇒ không có chip
- [ ] K7 — model drift ⇒ `rule_fallback`; ép ⇒ luôn gắn nhãn "bật thủ công"
- [ ] K8 — model hỏng ⇒ `sha_mismatch`, app không sập
- [ ] K9 — tắt model ⇒ quay về `ml-sim-v1`
- [ ] K10 — sandbox: 3 bảng đúng; vai khác Phú ⇒ 403
- [ ] K11 — bật/tắt ML **không** đổi kết quả ghép
- [ ] K12 — (khi tái huấn luyện) mã băm khớp, K1 + K2 vẫn đạt
