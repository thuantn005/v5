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
  jackpot_check.py       # xác định đúng kỳ "chia giải" Độc Đắc (21h ngày kế tiếp, jackpot > 12 tỷ)
  jackpot_watch.py       # "săn kỳ chia giải": báo SỚM 1 lần ngay khi jackpot vừa vượt 12 tỷ
  check_results.py       # đối chiếu dự đoán kỳ trước với kết quả thật đã ra, ghi lại trung thực
  predict.py             # điều phối: dự đoán, quyết định gửi tin, ghi log
  notify_ntfy.py         # gửi push notification qua ntfy.sh
data/all.csv             # dữ liệu lịch sử (tự cập nhật)
state/calibration.json   # kết quả backtest + ngưỡng (tự cập nhật)
state/predictions_log.csv# lịch sử mọi lần dự đoán + kết quả thật đối chiếu, để tự kiểm chứng độ chính xác
.github/workflows/predict.yml  # lịch chạy tự động 2 lần/ngày
```

## Bộ số "chọn ngược lại"

Ngoài bộ số chính (5 số điểm cao nhất), mỗi lần dự đoán mô hình cũng tính luôn bộ **ngược lại** — 5 số điểm THẤP nhất (kèm hạn chế cặp số hay đi cùng nhau, đảo ngược logic của bộ chính). Cả hai bộ đều được ghi vào `predictions_log.csv` và đối chiếu với kết quả thật qua `check_results.py`, để bạn tự so sánh xem bộ nào "trúng" nhiều hơn theo thời gian — về mặt lý thuyết, cả hai nên trúng ngang nhau vì xổ số là ngẫu nhiên.

## Quy tắc "kỳ chia giải Độc Đắc"

Theo quy định Vietlott: khi giải Độc Đắc vượt 12 tỷ đồng mà chưa ai trúng, kỳ quay 21h00 của **ngày kế tiếp** (không phải kỳ quay ngay sau đó nếu cùng ngày) mới là kỳ chia giải. `jackpot_check.py` implement đúng quy tắc này: chỉ báo `is_sharing_round=True` khi (a) jackpot > 12 tỷ, VÀ (b) kỳ sắp dự đoán đúng là kỳ 21h của ngày kế tiếp. Nếu không cào được số liệu jackpot (trang Vietlott/nguồn phụ thay đổi cấu trúc), script im lặng trả về `False` thay vì đoán bừa.

Có 2 tầng thông báo về jackpot:
1. **Báo sớm** (`jackpot_watch.py`): ngay khi jackpot vừa vượt 12 tỷ lần đầu trong chu kỳ, gửi 1 tin duy nhất báo trước ("sắp có kỳ chia giải") — không spam lặp lại khi vẫn đang trên ngưỡng.
2. **Báo đúng ngày** (`jackpot_check.py`): khi đến chính xác kỳ 21h ngày chia giải, gửi tin xác nhận kèm bộ số dự đoán.

## Theo dõi độ chính xác (tự động, trung thực)

Mỗi lần workflow chạy, `check_results.py` sẽ kiểm tra xem kỳ đã dự đoán trước đó đã có kết quả thật chưa; nếu có, nó tự điền vào `state/predictions_log.csv`: số thật đã ra, số trùng (main_hits 0-5), có trùng số đặc biệt không, và có trúng "jackpot" (5 số chính + đặc biệt) hay không. File này được commit lại repo mỗi lần chạy — bạn có thể mở bất cứ lúc nào để tự xem con số thật (trung bình số trùng nên dao động quanh mức ngẫu nhiên kỳ vọng ~0.71 số/5, không có gì đặc biệt nếu mô hình không có edge thật — và theo mọi backtest đã chạy, nó không có).


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

- `model.py`: đổi `SHORT_WINDOW`/`NEAR_WINDOW`, trọng số `W_SHORT`/`W_NEAR`/`W_LONG`/`W_GAP`/`PAIR_SYNERGY_WEIGHT` để thử biến thể khác. Công thức hiện tại (`0.40*z_ngắn + 0.30*z_gần - 0.15*z_dài + 0.15*(gap_ratio-1)` + bonus cặp synergy) mô phỏng theo phương pháp "Kết hợp ba dấu hiệu" (balanced signal) của [nhanaz-data.github.io/vietlott-prediction-web](https://nhanaz-data.github.io/vietlott-prediction-web/phuong-phap.html) — dự án thống kê độc lập, cùng tác giả với bộ dữ liệu. Ngay cả với công thức chặt chẽ hơn này, backtest walk-forward vẫn cho tương quan ~0 giữa confidence và số trúng thật — khớp với kết luận chính thức của dự án tham khảo: *"Chưa cách chọn nào thắng ngẫu nhiên ổn định."*
- `backtest_calibrate.py`: đổi `PERCENTILE_FOR_THRESHOLD` (mặc định 0.95) để báo thường xuyên hơn/ít hơn.
- `jackpot_check.py`: mang tính "best-effort" — Vietlott có thể đổi cấu trúc trang bất kỳ lúc nào khiến scraper không tìm được số liệu; khi đó script sẽ **im lặng bỏ qua** phần jackpot thay vì đoán bừa, để tránh báo sai.
- `predict.py`: chỉnh nội dung tin nhắn ntfy, mức priority, tags, v.v.
