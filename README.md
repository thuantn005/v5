# Vietlott Lotto 5/35 – Auto Backtest & Notify

Tự động lấy dữ liệu, backtest, dự đoán kỳ quay tiếp theo của **Lotto 5/35**, và gửi thông báo qua [ntfy](https://ntfy.sh) khi (a) điểm số nội bộ của mô hình ở mức bất thường cao, hoặc (b) sắp đến kỳ chia giải Độc Đắc.

## ⚠️ Đọc trước khi dùng

Lotto 5/35 là trò chơi hoàn toàn ngẫu nhiên — mỗi kỳ quay độc lập, mọi bộ số có xác suất bằng nhau bất kể lịch sử trước đó. Dự án này **không** và **không thể** tìm ra một "công thức thắng". Điểm số (confidence score) chỉ là một chỉ số heuristic (tần suất xuất hiện gần đây + độ trễ/"gan") — dùng để tạo ra một bộ số gợi ý và để quyết định *khi nào nên báo* (tránh spam mỗi kỳ), **không phải** để đánh giá xác suất trúng thật.

`scripts/backtest_calibrate.py` chạy walk-forward backtest trên toàn bộ lịch sử và tự ghi lại hệ số tương quan giữa "confidence" và số trúng thực tế vào `state/calibration.json`. Nếu bạn mở file đó ra và thấy tương quan gần 0 — đó chính xác là những gì mọi backtest trước đây trên dữ liệu này đã cho thấy. Ngưỡng thông báo (`notify_threshold_confidence`) chỉ kiểm soát **tần suất gửi tin**, không phải mức độ chính xác.

Dùng dự án này để giải trí, học thống kê/backtesting, và tự động hóa — không nên dùng để đưa ra quyết định tài chính.

## Cấu trúc

```
scripts/
  model.py               # logic tính điểm hybrid (tần suất + gap)
  fetch_data.py          # tải CSV kết quả mới nhất
  backtest_calibrate.py  # walk-forward backtest + tính ngưỡng thông báo
  jackpot_check.py       # kiểm tra khả năng đến "kỳ chia giải" Độc Đắc
  predict.py             # điều phối: dự đoán, quyết định gửi tin, ghi log
  notify_ntfy.py         # gửi push notification qua ntfy.sh
data/all.csv             # dữ liệu lịch sử (tự cập nhật)
state/calibration.json   # kết quả backtest + ngưỡng (tự cập nhật)
state/predictions_log.csv# lịch sử mọi lần dự đoán, để tự kiểm chứng độ chính xác
.github/workflows/predict.yml  # lịch chạy tự động 2 lần/ngày
```

## Nguồn dữ liệu

Mặc định lấy từ dataset công khai [`NhanAZ-Data/vietlott-data-research`](https://github.com/NhanAZ-Data/vietlott-data-research) (đã tổng hợp kết quả Lotto 5/35 từ nguồn thứ cấp, cập nhật gần như hàng ngày). Nếu bạn có scraper riêng (ví dụ endpoint AjaxPro đã reverse-engineer), chỉ cần sửa `SOURCE_URL` trong `scripts/fetch_data.py` — phần còn lại chỉ cần file CSV có cột `draw_id` và `result_json` cùng định dạng.

## Thiết lập trên GitHub (5 phút)

1. Tạo repo mới trên GitHub (ví dụ `vietlott-lotto535-autopredict`), để **Public** hoặc **Private** đều được (Private thì Actions vẫn chạy free trong giới hạn phút miễn phí hàng tháng).
2. Upload toàn bộ nội dung thư mục này vào repo (giữ nguyên cấu trúc).
3. Vào tab **Actions** của repo, bấm **"I understand my workflows, enable them"** nếu được hỏi.
4. Workflow `predict.yml` sẽ tự chạy theo lịch (10:00 và 18:00 UTC = 17:00 và 01:00 giờ Việt Nam, sau mỗi kỳ quay 13:00/21:00). Bạn cũng có thể chạy tay: **Actions → Lotto 5/35 Predict & Notify → Run workflow**.
5. Cài app **ntfy** trên điện thoại (CH Play/App Store: tìm "ntfy"), mở app → bấm **+** → nhập topic `lotto535-thuan` → **Subscribe**. Xong — không cần đăng ký tài khoản, không cần cấu hình thêm gì trong repo vì topic đã để sẵn trong workflow.

> Lưu ý: ntfy.sh là server công khai miễn phí — bất kỳ ai biết tên topic `lotto535-thuan` cũng có thể subscribe hoặc gửi tin vào đó. Nếu muốn riêng tư hơn, có thể đổi thành một tên topic dài/khó đoán hơn (sửa ở `predict.yml` và trong app ntfy), hoặc tự host ntfy server riêng.

## Chạy thử ở máy local

```bash
pip install -r requirements.txt
python scripts/fetch_data.py
python scripts/backtest_calibrate.py
NTFY_TOPIC=lotto535-thuan python scripts/predict.py
```

## Tùy chỉnh

- `model.py`: đổi `DEFAULT_WINDOW`, `FREQ_WEIGHT`, `GAP_WEIGHT` để thử các biến thể khác (giống các thử nghiệm hybrid weighted scoring trước đây).
- `backtest_calibrate.py`: đổi `PERCENTILE_FOR_THRESHOLD` (mặc định 0.95) để báo thường xuyên hơn/ít hơn.
- `jackpot_check.py`: mang tính "best-effort" — Vietlott có thể đổi cấu trúc trang bất kỳ lúc nào khiến scraper không tìm được số liệu; khi đó script sẽ **im lặng bỏ qua** phần jackpot thay vì đoán bừa, để tránh báo sai.
- `predict.py`: chỉnh nội dung tin nhắn ntfy, mức priority, tags, v.v.

## Theo dõi độ chính xác

Mỗi lần chạy, `state/predictions_log.csv` được ghi thêm một dòng (kỳ dựa vào, bộ số dự đoán, confidence, ngưỡng, có báo tin hay không). Vì file này được commit lại vào repo, bạn có thể mở ra bất cứ lúc nào để tự đối chiếu với kết quả thật và kiểm chứng xem mô hình có thực sự "hơn ngẫu nhiên" hay không — theo đúng tinh thần backtest trung thực.
