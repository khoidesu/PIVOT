# Hướng dẫn huấn luyện ETA trên Kaggle (dữ liệu MÔ PHỎNG)

> ⚠️ Dữ liệu do bộ sinh tạo ra (`eta_generator_params.json`). Mô hình học lại chính công thức đó, nên kết quả **chỉ chứng minh quy trình**, không chứng minh
> độ chính xác ngoài đời. Khi trình bày hãy nhấn vào cơ chế (chia theo thời gian, cổng promote, tự hạ về luật), không phải con số.

## Các bước
1. Trên Kaggle: **Create → New Dataset**, tải lên `eta_trips.csv` và `eta_schema.json` (đặt tên dataset tuỳ ý, ví dụ `eta-sim`).
2. **Create → New Notebook** → *File → Import Notebook* → chọn `eta_train_kaggle.ipynb`. Bên phải: **Add Input** → chọn dataset vừa tạo.
3. Bật **Internet** (Settings) nếu notebook báo thiếu `onnx`/`onnxruntime` (ô đầu tiên sẽ tự cài). GPU **không cần** (dữ liệu nhỏ, CPU chạy vài chục giây).
4. **Run All**. Notebook tự: kiểm tra không rò rỉ → so baseline → huấn luyện P50/P90 → hiệu chỉnh P90 → đánh giá trên `test` → xuất ONNX → kiểm tra ONNX khớp PyTorch → ghi model card.
5. Tải 2 file ở `/kaggle/working/` về máy: **`eta_model.onnx`** và **`eta_model_card.json`**, rồi gửi lại.

## Kết quả mong đợi (để biết có chạy đúng không)
- Mô hình thắng `rule_const_min` (hằng số 90) rất rõ; thắng `rule_dist_min`/`baseline_median_min` ít hơn.
- Do **drift cố ý** ở 2 tháng cuối, độ phủ P90 trên `test` thường **thấp hơn** trên `calib`; có thể rơi ra ngoài [0,85; 0,97] → cổng promote báo "hạ về luật". Đây là hành vi **đúng và có chủ đích** (minh hoạ cổng phát hiện trôi), không phải lỗi.

## Hợp đồng đầu vào/đầu ra của model (backend sẽ dựa vào đây)
- Đầu vào `features`: `float32 [N, 12]`, thứ tự cột = `input_order` trong `eta_schema.json` (chuẩn hoá đã **nhúng trong ONNX**).
- Đầu ra `eta`: `float32 [N, 2]` = (`p50_minutes`, `p90_minutes`), bảo đảm `p90 >= p50`.
