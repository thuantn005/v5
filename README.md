# Vietlott Lotto 5/35 – Multi-Model Ensemble Auto Backtest & Notify

Tự động lấy dữ liệu, chạy **10 model dự đoán độc lập**, tự tối ưu tham số theo lịch, backtest trung thực (so với baseline ngẫu nhiên bằng lý thuyết hypergeometric, không dùng ROI dễ gây hiểu lầm), kết hợp **Ensemble Voting**, gửi thông báo qua [ntfy](https://ntfy.sh), và xuất **Dashboard** trên GitHub Pages.

## ⚠️ Đọc trước khi dùng

Lotto 5/35 là trò chơi hoàn toàn ngẫu nhiên — mỗi kỳ quay độc lập, mọi bộ số có xác suất bằng nhau bất kể lịch sử trước đó. **Xác suất trúng Jackpot luôn cố định ở mức 1/324.632, bất kể chọn số theo cách nào.** Không có model, ensemble, hay auto-tuning nào trong dự án này làm thay đổi được điều đó.

`scripts/backtest_all.py` so sánh trung thực từng model với baseline ngẫu nhiên bằng test thống kê (p-value), thay vì chỉ số ROI (đã kiểm chứng dễ bị 1 lần trúng may mắn ở giải hiếm làm sai lệch hoàn toàn — xem phần "Vì sao không dùng ROI" bên dưới). Kết quả nhất quán qua nhiều lần backtest: **không model nào có p-value < 0.05**, tức không đủ bằng chứng để nói model nào thật sự "hơn ngẫu nhiên".

Dùng dự án này để giải trí, học thống kê/backtesting, và tự động hóa — không nên dùng để đưa ra quyết định tài chính.

## Vì sao không dùng ROI để xếp hạng model

Repo tham khảo `vietvudanh/vietlott-data` xếp hạng model bằng ROI mô phỏng, nhưng ngay cả `Random Strategy` (chọn hoàn toàn ngẫu nhiên) cũng báo ROI dương >1000%. Nguyên nhân: với xác suất khớp 5/6 (Power 6/55) ≈ 0.0000101/vé, kỳ vọng số lần trúng giải 5 tỷ qua 40.200 vé mô phỏng chỉ ≈ 0.41 lần — bất kỳ ai "may mắn" trúng 1 lần cũng đủ làm ROI nhảy vọt, che lấp hoàn toàn hiệu năng thật. Vì vậy hệ thống này dùng **số khớp trung bình + p-value so với baseline ngẫu nhiên chính xác (hypergeometric)** thay vì ROI.

## Cấu trúc

```
scripts/
  model.py                    # Draw parsing + công thức "balanced signal" gốc (3 cửa sổ z-score)
  strategies.py                # 10 model: hot/cold/long_absence/exponential_decay/pair_frequency/
                                #   markov_chain/not_repeat/pattern/balanced_signal/crowd_avoidance
  jackpot_hunter.py             # Chế độ "Jackpot Hunter": né số công cụ tham khảo công khai (giảm rủi ro chia giải)
  tuning.py                    # Auto-tune tham số từng model (grid search, train/holdout,
                                #   chỉ chạy lại mỗi 7 ngày -- "theo lịch")
  backtest_all.py              # Backtest walk-forward mọi model, so p-value với baseline ngẫu nhiên
  ensemble.py                  # Ensemble Voting: trung bình chuẩn hóa điểm số 10 model -> 1 bộ số
  ensemble_calibrate.py        # Backtest + tính ngưỡng thông báo cho ensemble
  multi_log.py                 # Log JSONL mọi dự đoán (ensemble + từng model) + đối chiếu kết quả thật
  jackpot_check.py             # Xác định đúng kỳ "chia giải" Độc Đắc (21h ngày kế tiếp, jackpot > 12 tỷ)
  jackpot_watch.py             # "Săn kỳ chia giải": báo SỚM 1 lần ngay khi jackpot vừa vượt 12 tỷ
  notify_ntfy.py                # Gửi push notification qua ntfy.sh
  fetch_data.py                 # Tải CSV kết quả mới nhất
  run_pipeline.py               # Điều phối toàn bộ: tune -> backtest -> ensemble -> jackpot -> notify -> log
  generate_dashboard_data.py    # Tổng hợp docs/data.json cho Dashboard

data/all.csv                    # Dữ liệu lịch sử (tự cập nhật)
state/
  tuned_params.json             # Tham số đã tối ưu cho từng model
  tuning_report.json            # Kết quả tuning (train vs holdout, để tự kiểm tra overfit)
  tuning_schedule.json          # Lần tuning gần nhất (kiểm soát lịch tự tối ưu)
  model_leaderboard.json        # Bảng xếp hạng backtest mới nhất (trung thực, có p-value)
  ensemble_calibration.json     # Ngưỡng thông báo của ensemble
  ensemble_log.jsonl            # Lịch sử mọi dự đoán (ensemble + 10 model) + kết quả thật đối chiếu
  jackpot_state.json             # Trạng thái chu kỳ jackpot (chống spam báo sớm)
docs/
  index.html                     # Dashboard (GitHub Pages)
  data.json                      # Dữ liệu cho dashboard (tự sinh mỗi lần chạy)
.github/workflows/predict.yml    # Lịch chạy tự động 2 lần/ngày
```

## 10 Model chiến lược

Dịch ý tưởng từ [`vietvudanh/vietlott-data`](https://github.com/vietvudanh/vietlott-data/tree/main/src/machine_learning/strategies) (gốc cho Power 6/55), điều chỉnh cho Lotto 5/35 (pool 1-35, chọn 5 số):

| Model | Ý tưởng |
|---|---|
| `hot_numbers` | Ưu tiên số xuất hiện nhiều nhất trong cửa sổ gần đây |
| `cold_numbers` | Ưu tiên số xuất hiện ít nhất (ngược lại hot) |
| `long_absence` | Ưu tiên số "gan" lâu nhất chưa về |
| `exponential_decay` | Trọng số giảm dần theo cấp số nhân, kỳ càng gần càng nặng |
| `pair_frequency` | Ưu tiên số hay đi cùng các số đang "hot" |
| `markov_chain` | Xác suất chuyển trạng thái: số nào hay về sau các số của kỳ gần nhất |
| `not_repeat` | Né số vừa về ở vài kỳ gần nhất |
| `pattern` | Ưu tiên "vùng số" (bucket khoảng) xuất hiện nhiều bất thường |
| `crowd_avoidance` | Ưu tiên số ngoài "vùng ngày sinh" (1-31) — không tăng tỷ lệ trúng, chỉ giảm rủi ro CHIA giải nếu trúng |
| `balanced_signal` | Công thức 3 cửa sổ z-score tham khảo từ nhanaz-data (đã dùng từ trước) |

## 🏹 Chế độ "Jackpot Hunter"

`jackpot_hunter.py` — dành cho người thật sự muốn tối ưu theo góc nhìn "săn Jackpot" chứ không phải "tăng tỷ lệ trúng" (2 việc khác nhau hoàn toàn):

- **Sự thật duy nhất có ý nghĩa kinh tế thật**: Vietlott chia đều giải Độc Đắc nếu nhiều vé cùng trúng trong 1 kỳ (pari-mutuel). Nếu nhiều người dùng chung 1 công cụ dự đoán công khai (như nhanaz-data) và cùng trúng, họ phải chia nhau giải thưởng.
- Script tự tải **sổ dự đoán đã khóa trước, có hash chain chống sửa** của `nhanaz-data/vietlott-prediction-web` (`predictions/ledger.jsonl`) — không đoán mò, dùng đúng số họ đã công bố công khai cho kỳ tới.
- Lấy bộ số Ensemble của hệ thống này làm nền, rồi **loại trừ hoàn toàn** mọi số nằm trong dự đoán công khai đó, chọn lại từ phần còn lại.
- Nếu không tải được sổ dự đoán tham khảo (mạng lỗi, repo đổi cấu trúc), tự động dùng nguyên bộ Ensemble và báo rõ `reference_available: false` — không đoán bừa.
- Bộ số Hunter xuất hiện riêng trong thông báo ntfy (khi có gửi tin) và trong dashboard, tách biệt với bộ Ensemble chính.

**Nhắc lại**: bộ Hunter không có xác suất trúng cao hơn bộ Ensemble hay bất kỳ bộ nào khác — nó chỉ khác về mặt "nếu trúng thì đỡ phải chia" (giả định người khác dùng chung công cụ tham khảo và cùng trúng).

## Tự động tối ưu tham số (theo lịch)

`tuning.py` chạy grid search nhỏ cho mỗi model, **chọn tham số trên tập train (70% lịch sử đầu)**, rồi **đánh giá độc lập trên tập holdout (30% còn lại chưa từng dùng để chọn)** — tránh overfit toàn bộ lịch sử. Chỉ chạy lại mỗi 7 ngày (`TUNE_EVERY_DAYS`), không phải mỗi lần dự đoán, để tránh tham số "nhảy" liên tục theo nhiễu. Xem `state/tuning_report.json` — nếu `holdout_avg_hits` thường xuyên thấp hơn nhiều so với `train_avg_hits`, đó là dấu hiệu overfit rõ ràng (đã quan sát thấy với `markov_chain` trong thử nghiệm: train 0.82 nhưng holdout chỉ 0.64).

## Ensemble Voting

`ensemble.py` chuẩn hóa (min-max) điểm số mỗi model về [0,1] rồi lấy **trung bình cộng đều** (không theo trọng số hiệu năng quá khứ, vì `model_leaderboard.json` cho thấy không model nào có edge thật đáng tin để ưu tiên trọng số cao hơn — làm vậy sẽ chỉ là fit nhiễu). Bộ số cuối cùng = 5 số có điểm ensemble cao nhất.

## Vì sao workflow đôi khi không chạy đúng giờ đã đặt (và cách đã khắc phục)

GitHub Actions chạy `schedule` theo kiểu **best-effort**, không đảm bảo đúng giờ tuyệt đối — đặc biệt hay bị trễ hoặc bỏ lỡ nếu đặt vào **đúng phút 00** của giờ, vì đó là lúc hàng loạt workflow khác trên toàn GitHub cùng kích hoạt, gây nghẽn hàng đợi (giới hạn nền tảng, GitHub công bố công khai).

**Yêu cầu: phải có kết quả trong vòng 1 tiếng sau mỗi kỳ quay.** Đã khắc phục bằng 3 cách:

1. **Chạy sớm hơn nhiều**: primary chạy ở phút **+35** sau mỗi kỳ quay (13:35 & 21:35 giờ VN), backup ở phút **+50** (13:50 & 21:50) — cả hai đều nằm trong khung 1 tiếng.
2. **`fetch_data.py` giờ LUÔN kiểm tra cả nguồn nhanh** (`fallback_scraper.py` cào trực tiếp minhchinh.com) **song song với nguồn chính** (NhanAZ-Data), không đợi nguồn chính lỗi mới dùng — vì NhanAZ-Data quan sát được là hay cập nhật trễ 2-4 tiếng, không kịp yêu cầu 1 tiếng. minhchinh.com cập nhật nhanh hơn nhiều (thường trong vài chục phút), nên hệ thống luôn ưu tiên dùng bất kỳ nguồn nào có kết quả mới nhất trước.
3. **Cơ chế chống trùng** (`already_predicted()`): nếu lượt +35 phút chưa có kết quả mới, sẽ tự bỏ qua (không báo/log gì); lượt +50 phút sẽ thử lại. Nếu lượt +35 đã thành công, lượt +50 tự nhận biết và bỏ qua để tránh trùng lặp.

## Bộ số "chọn ngược lại" (model balanced_signal)

Model `balanced_signal` vẫn giữ khả năng tính bộ số ngược lại (5 số điểm thấp nhất) — xem `model.py::predict_next()`. Tính năng này độc lập với hệ ensemble mới.

## Quy tắc "kỳ chia giải Độc Đắc"

Theo quy định Vietlott: khi giải Độc Đắc vượt 12 tỷ đồng mà chưa ai trúng, kỳ quay 21h00 của **ngày kế tiếp** (không phải kỳ quay ngay sau đó nếu cùng ngày) mới là kỳ chia giải. `jackpot_check.py` chỉ báo `is_sharing_round=True` khi (a) jackpot > 12 tỷ, VÀ (b) kỳ sắp dự đoán đúng là kỳ 21h của ngày kế tiếp.

Có 3 tầng thông báo:
1. **Báo sớm** (`jackpot_watch.py`): ngay khi jackpot vừa vượt 12 tỷ lần đầu trong chu kỳ.
2. **Báo đúng ngày**: khi đến chính xác kỳ 21h ngày chia giải, kèm bộ số ensemble.
3. **Báo mù** (`jackpot_watch.check_scrape_alert`): nếu **mọi nguồn tra cứu jackpot đều lỗi** (site sập / đổi HTML), hệ thống không thể tự xác định kỳ chia giải — gửi cảnh báo 1 lần để bạn kiểm tra thủ công, tránh im lặng bỏ lỡ. Tự tắt khi tra cứu hoạt động lại.

## Dashboard (GitHub Pages)

`docs/index.html` đọc `docs/data.json` (tự sinh mỗi lần workflow chạy) và hiển thị:
- 📈 Biểu đồ hiệu năng theo thời gian (trung bình khớp lũy kế từng model)
- 🏆 Bảng xếp hạng model (kèm p-value, có/không ý nghĩa thống kê)
- 🎯 Bộ số dự đoán mới nhất (ensemble + từng model)
- 📊 Lịch sử các kỳ quay và kết quả thật
- 📉 Độ chính xác thực tế từng model (từ các kỳ đã triển khai thật, không phải backtest lịch sử)

**Kích hoạt GitHub Pages** (1 lần): repo → Settings → Pages → Source: **Deploy from a branch** → Branch: `main`, folder **`/docs`** → Save. Sau đó dashboard sẽ có ở `https://<username>.github.io/<repo>/`.

## Nguồn dữ liệu (có dự phòng tự động, 2 tầng)

**Tầng 1 — nguồn chính** (`fetch_data.py`): thử lần lượt 3 mirror — GitHub raw, jsdelivr CDN, statically.io CDN, đều trỏ về cùng dataset [`NhanAZ-Data/vietlott-data-research`](https://github.com/NhanAZ-Data/vietlott-data-research) (hạ tầng khác nhau nên nếu 1 cái sập/rate-limit thì cái kia thường vẫn chạy). Thành công thì **thay thế toàn bộ** `data/all.csv` bằng bản đầy đủ mới nhất.

**Tầng 2 — scraper độc lập thật sự** (`fallback_scraper.py`): chỉ kích hoạt khi **cả 3 mirror ở Tầng 1 đều lỗi**. Đây không phải mirror của cùng 1 dataset — nó tự cào trực tiếp bảng "15 kỳ gần nhất" từ `minhchinh.com` (nguồn hoàn toàn khác), rồi **chỉ bổ sung** (append) các kỳ mới chưa có trong `data/all.csv`, không thay thế toàn bộ file. Mỗi dòng được bổ sung theo cách này gắn nhãn rõ `"data_source": "minhchinh_com_fallback_scraper"` và `"validation_status": "unverified_fallback"` trong dữ liệu để minh bạch nguồn gốc.

Nếu **cả 2 tầng đều lỗi**: giữ nguyên `data/all.csv` hiện có, không ghi đè, không crash — pipeline tiếp tục chạy trên dữ liệu cũ.

**Giá trị Jackpot** (`jackpot_check.py`): 5 nguồn dự phòng riêng — vietlott.vn (chính thức), xsmn.mobi, minhchinh.com, onbit.vn, ketquadientoan.com. Nếu tất cả lỗi, trả về `jackpot_vnd: null` và không báo tin jackpot thay vì đoán bừa.

## Thiết lập trên GitHub

1. Tạo repo mới, upload toàn bộ nội dung thư mục này.
2. Tab **Actions** → bật workflow nếu được hỏi.
3. Workflow `predict.yml` tự chạy 2 lần/ngày (14:00 & 22:00 giờ VN). Chạy tay: **Actions → Run workflow**.
4. (Tuỳ chọn) Bật **GitHub Pages** như hướng dẫn ở trên để có dashboard.
5. Cài app **ntfy**, subscribe topic `lotto535-thuan`.

## Chạy thử ở máy local

```bash
pip install -r requirements.txt
python scripts/fetch_data.py
python scripts/run_pipeline.py
python scripts/generate_dashboard_data.py
```

Lần chạy đầu tiên sẽ tự tạo toàn bộ file trong `state/` (tuning, backtest, calibration) vì chưa có gì tồn tại.

## Tùy chỉnh

- `strategies.py`: thêm model mới bằng cách viết 1 hàm cùng interface `(history, pool_min, pool_max, k, use_special, params) -> dict[int, float]`, rồi thêm vào `STRATEGIES` + `DEFAULT_PARAMS`.
- `tuning.py`: đổi `PARAM_GRID` để mở rộng/thu hẹp không gian tìm kiếm tham số, hoặc `TUNE_EVERY_DAYS` để đổi lịch tối ưu.
- `ensemble.py`: hiện dùng trọng số đều; có thể đổi sang trọng số theo `model_leaderboard.json` nếu muốn, nhưng nên cân nhắc kỹ vì rủi ro fit nhiễu (xem ghi chú trong file).
- `jackpot_check.py`: mang tính "best-effort" — nếu Vietlott đổi cấu trúc trang, script im lặng bỏ qua thay vì đoán bừa.
