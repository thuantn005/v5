# Vietlott Lotto 5/35 – Multi-Model Ensemble Auto Backtest & Notify

Tự động lấy dữ liệu, chạy **3 model dự đoán độc lập** (chọn lọc, đa dạng), tự tối ưu tham số theo lịch, backtest trung thực (so với baseline ngẫu nhiên bằng lý thuyết hypergeometric, không dùng ROI dễ gây hiểu lầm), kết hợp **Ensemble Voting**, gửi thông báo qua [ntfy](https://ntfy.sh), và xuất **Dashboard** trên GitHub Pages.

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
  strategies.py                # 3 model ACTIVE: gap_zscore/momentum/crowd_avoidance.
                                #   Các model khác (hot_numbers/bayesian_frequency/exponential_decay/
                                #   pair_frequency/markov_chain/entropy_diversity/pattern/
                                #   balanced_signal) vẫn định nghĩa sẵn nhưng TẮT — thêm 1 dòng
                                #   vào STRATEGIES để bật lại. (+ random_repeat: chỉ để backtest)
  references.py                 # 3 bộ số tham chiếu/so sánh (ngẫu nhiên công bằng, ngẫu nhiên có lặp, giống nhanaz-data)
  tuning.py                    # Auto-tune tham số từng model (grid search, train/holdout,
                                #   chỉ chạy lại mỗi 7 ngày -- "theo lịch")
  backtest_all.py              # Backtest walk-forward mọi model, so p-value với baseline ngẫu nhiên
  ensemble.py                  # Ensemble Voting: gộp điểm 3 model (nhóm tương quan + trọng số p-value) -> 1 bộ số
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
  ensemble_log.jsonl            # Lịch sử mọi dự đoán (ensemble + 3 model active) + kết quả thật đối chiếu
  jackpot_state.json             # Trạng thái chu kỳ jackpot (chống spam báo sớm)
docs/
  index.html                     # Dashboard (GitHub Pages)
  data.json                      # Dữ liệu cho dashboard (tự sinh mỗi lần chạy)
.github/workflows/predict.yml    # Lịch chạy tự động 2 lần/ngày (~2h sau mỗi kỳ quay)
```

## Model chiến lược (3 active + thư viện tắt)

Dịch ý tưởng từ [`vietvudanh/vietlott-data`](https://github.com/vietvudanh/vietlott-data/tree/main/src/machine_learning/strategies) (gốc cho Power 6/55), điều chỉnh cho Lotto 5/35 (pool 1-35, chọn 5 số).

**Ensemble hiện dùng đúng 3 model active** (✅) — cố ý chọn 3 tín hiệu khác biệt nhau nhất, không giữ nhiều model "họ tần suất" gần trùng:

| Model | Trạng thái | Ý tưởng |
|---|---|---|
| **★✅ `gap_zscore`** | active | Số "gan" xét theo **nhịp riêng của từng số**: lệch bao nhiêu so với khoảng cách trung bình của chính nó (z-score), không phải gan tuyệt đối |
| **★✅ `momentum`** | active | Số có tần suất cửa sổ ngắn **đang tăng** vượt baseline cửa sổ dài của chính nó (xu hướng/gia tốc), khác với "hot" mức tuyệt đối |
| **✅ `crowd_avoidance`** | active | Ưu tiên số ít bị đám đông chọn (ngoài vùng 1-31, số tháng, số "may mắn") — **đòn bẩy EV thật duy nhất**: không tăng tỷ lệ trúng, chỉ giảm rủi ro CHIA giải nếu trúng |
| `hot_numbers` | tắt (thư viện) | Ưu tiên số xuất hiện nhiều nhất trong cửa sổ gần đây |
| `bayesian_frequency` | tắt | Ước lượng xác suất từng số theo hậu nghiệm Bayes (Laplace/add-α smoothing) |
| `exponential_decay` | tắt | Trọng số giảm dần theo cấp số nhân, kỳ càng gần càng nặng |
| `pair_frequency` | tắt | Ưu tiên số hay đi cùng các số đang "hot" |
| `markov_chain` | tắt | Xác suất chuyển trạng thái: số nào hay về sau các số của kỳ gần nhất |
| `entropy_diversity` | tắt | Dựng vé **trải đều** tối đa entropy phủ dải số (1 đại diện/bucket) |
| `pattern` | tắt | Ưu tiên "vùng số" (bucket khoảng) xuất hiện nhiều bất thường |
| `balanced_signal` | tắt | Công thức 3 cửa sổ z-score tham khảo từ nhanaz-data |

> **Roster đã được cắt còn 3 model active.** 8 model còn lại vẫn **định nghĩa sẵn trong `strategies.py`** (thư viện tắt) — bật lại chỉ cần thêm 1 dòng vào `STRATEGIES` (+ `DEFAULT_PARAMS`/`PARAM_GRID`). Lịch sử: 3 model "ngụy biện con bạc" cũ (`cold_numbers`/`long_absence`/`not_repeat`) đã bị thay/bỏ, `chi_square_uniformity` bị loại vì trùng `bayesian_frequency`, rồi roster gọn về 3 tín hiệu khác biệt nhất. **Không thay đổi nào tăng xác suất trúng** — xổ số vẫn ngẫu nhiên (1/324.632). `random_repeat` (chọn ngẫu nhiên **có lặp lại**) chỉ dùng để backtest so sánh (không nằm trong ensemble): nó **kém hơn** baseline vì số trùng làm phí vị trí.

## 📏 Mốc so sánh & tham chiếu (`references.py`)

Thay cho "Jackpot Hunter" cũ, mỗi kỳ hệ thống tạo **3 bộ số tham chiếu** hiển thị cạnh Ensemble (trong thông báo ntfy + dashboard + log, có đối chiếu kết quả thật như mọi model). Chúng **không** nằm trong ensemble và **không** tuyên bố có edge — chỉ là thước đo trung thực:

| Tham chiếu | Ý nghĩa |
|---|---|
| **Mốc so sánh công bằng** (`random_fair`) | 5 số **khác nhau** chọn ngẫu nhiên đều — đây là *null model đúng*: mọi vé xác suất như nhau, nên model nào không thắng nổi mốc này qua thời gian là **không có kỹ năng thật**. |
| **Chọn ngẫu nhiên có thể lặp lại** (`random_repeat`) | 5 số lấy mẫu **có hoàn lại** (cho phép trùng) — mốc *tệ hơn* có chủ đích: số trùng làm phí vị trí, kỳ vọng khớp thấp hơn mốc công bằng. |
| **Giống nhanaz-data** (`nhanaz`) | Mô phỏng dự đoán của trang công khai [nhanaz-data](https://nhanaz-data.github.io/vietlott-prediction-web/?product=lotto535#du-doan): lấy **đồng thuận** (5 số được nhiều chiến lược của họ gợi ý nhất) từ sổ ledger đã khóa, để so trực tiếp Ensemble với công cụ phổ biến đó. Nếu không tải được thì đánh dấu `available: false`. |

Số ngẫu nhiên được **seed theo mã kỳ** (`target_draw_id`) nên tái lập được/kiểm toán được. **Mục đích chính:** cho thấy Ensemble **không hơn** mốc ngẫu nhiên công bằng — đúng bản chất trò chơi.

## Tự động tối ưu tham số (theo lịch)

`tuning.py` chạy grid search nhỏ cho mỗi model, **chọn tham số trên tập train (70% lịch sử đầu)**, rồi **đánh giá độc lập trên tập holdout (30% còn lại chưa từng dùng để chọn)** — tránh overfit toàn bộ lịch sử. Chỉ chạy lại mỗi 7 ngày (`TUNE_EVERY_DAYS`), không phải mỗi lần dự đoán, để tránh tham số "nhảy" liên tục theo nhiễu. Xem `state/tuning_report.json` — nếu `holdout_avg_hits` thường xuyên thấp hơn nhiều so với `train_avg_hits`, đó là dấu hiệu overfit rõ ràng (đã quan sát thấy với `markov_chain` trong thử nghiệm: train 0.82 nhưng holdout chỉ 0.64).

## Ensemble Voting

`ensemble.py` chuẩn hóa (min-max) điểm mỗi model về [0,1], rồi gộp lại với **2 tinh chỉnh** thay cho trung bình cộng đều thuần túy:

1. **Nhóm model tương quan** (correlation grouping): các model họ tần suất/gần đây (ví dụ `hot_numbers`, `bayesian_frequency`, `exponential_decay`) dễ cho bộ số gần giống nhau → tương quan cao. Nếu để nguyên, một cụm model giống nhau sẽ "bỏ phiếu" áp đảo một model khác biệt chỉ vì trùng lặp. Nên trước khi gộp, các model có vector điểm tương quan ≥ 0.9 được gom thành 1 nhóm và **thu về 1 đại diện** (trung bình nhóm) → mỗi *tín hiệu độc lập* chỉ có 1 phiếu thực. (Bản trùng rõ nhất, `chi_square_uniformity`, đã được loại hẳn khỏi bộ model.)
2. **Trọng số theo p-value**: mỗi nhóm được nhân trọng số `(1 − p_value)` từ backtest gần nhất, để model "khó phân biệt với ngẫu nhiên hơn" đếm nhẹ hơn.

> ⚠️ **Trung thực:** sau hiệu chỉnh Bonferroni (xem dưới), **không model nào đạt ý nghĩa thống kê** — nên trọng số p-value chủ yếu khuếch đại dao động ngẫu nhiên, đúng cái rủi ro "fit nhiễu" mà bản cũ cảnh báo. Vì vậy dải trọng số được **giữ hẹp có chủ đích** (sàn ~0.1) và hiển thị công khai trên dashboard để không bị hiểu nhầm thành "có edge". Khi nào một model thật sự đạt ý nghĩa-sau-hiệu-chỉnh qua nhiều giai đoạn, trọng số này mới phản ánh điều gì đó thật; hiện tại nó gần như đều.

## Độ chặt chẽ thống kê của backtest

`backtest_all.py` (→ `state/model_leaderboard.json`) ngoài trung bình số trúng & p-value hai phía, còn báo cáo:
- **Khoảng tin cậy 95%** (`avg_main_hits_ci95`) cho trung bình trúng — nếu khoảng này bao trùm mốc ngẫu nhiên 0.7143 thì model **không phân biệt được** với may rủi.
- **Hiệu chỉnh đa kiểm định Bonferroni**: test 3 model cùng lúc thì ~1 model sẽ trông "có ý nghĩa" ở mức 0.05 thuần do may. `significant_after_bonferroni` dùng ngưỡng chặt hơn `0.05/3 ≈ 0.0167` — đây mới là mốc trung thực. (Thực tế: không model nào vượt.)

## Vì sao workflow đôi khi không chạy đúng giờ đã đặt (và cách đã khắc phục)

GitHub Actions chạy `schedule` theo kiểu **best-effort**, không đảm bảo đúng giờ tuyệt đối — hay bị trễ (thực tế quan sát được có lúc trễ tới ~5 tiếng) hoặc bỏ lỡ, đặc biệt nếu đặt vào **đúng phút 00** của giờ, vì đó là lúc hàng loạt workflow khác trên toàn GitHub cùng kích hoạt gây nghẽn hàng đợi (giới hạn nền tảng, GitHub công bố công khai).

**Lịch: chạy ~2 tiếng sau mỗi kỳ quay** (15:00 & 23:00 giờ VN). Chọn 2 tiếng để cả nguồn nhanh lẫn nguồn chính (có thể trễ 2-4 tiếng) và **giá trị jackpot** (dùng cho cảnh báo kỳ chia giải) đều kịp công bố. Độ tin cậy được đảm bảo bằng 3 cách:

1. **Tránh phút :00**: primary chạy ở phút **:07** (15:07 & 23:07 giờ VN), backup ở phút **:27** (15:27 & 23:27) — off-peak nên ít bị nghẽn hàng đợi hơn.
2. **`fetch_data.py` LUÔN kiểm tra cả nguồn nhanh** (`fallback_scraper.py` cào trực tiếp minhchinh.com) **song song với nguồn chính** (NhanAZ-Data), luôn ưu tiên nguồn nào có kết quả mới nhất trước.
3. **Chống trùng + chịu được trễ** (`already_predicted()` / `resolve_all()`): pipeline idempotent theo từng kỳ, nên dù GitHub chạy trễ vài tiếng, chạy dư, hay bỏ lỡ 1 lượt thì lượt nào thực sự chạy cũng làm đúng **một lần duy nhất**; biên độ 2 tiếng hấp thụ phần trễ. Lịch `schedule` chỉ chạy từ nhánh mặc định (`main`) và bị GitHub tự tắt sau 60 ngày repo không có commit — bước tự commit hằng ngày giữ cho lịch luôn sống.

## Bộ số "chọn ngược lại" (model balanced_signal)

Model `balanced_signal` vẫn giữ khả năng tính bộ số ngược lại (5 số điểm thấp nhất) — xem `model.py::predict_next()`. Tính năng này độc lập với hệ ensemble mới.

## Quy tắc "kỳ chia giải Độc Đắc"

Theo quy định Vietlott: khi giải Độc Đắc vượt 12 tỷ đồng mà chưa ai trúng, kỳ quay 21h00 của **ngày kế tiếp** (không phải kỳ quay ngay sau đó nếu cùng ngày) mới là kỳ chia giải. `jackpot_check.py` chỉ báo `is_sharing_round=True` khi (a) jackpot > 12 tỷ, VÀ (b) kỳ sắp dự đoán đúng là kỳ 21h của ngày kế tiếp.

Có 3 tầng thông báo:
1. **Báo sớm** (`jackpot_watch.py`): ngay khi jackpot vừa vượt 12 tỷ lần đầu trong chu kỳ.
2. **Báo đúng ngày**: khi đến chính xác kỳ 21h ngày chia giải, kèm bộ số ensemble.
3. **Báo mù** (`jackpot_watch.check_scrape_alert`): nếu **mọi nguồn tra cứu jackpot đều lỗi** (site sập / đổi HTML), hệ thống không thể tự xác định kỳ chia giải — gửi cảnh báo 1 lần để bạn kiểm tra thủ công, tránh im lặng bỏ lỡ. Tự tắt khi tra cứu hoạt động lại.

## 🏆 Báo khi dự đoán TRÚNG (5 số chính + đặc biệt)

Khi đối chiếu kết quả thật (`multi_log.resolve_all()`), nếu **bất kỳ** bộ số đã dự đoán (Ensemble, các bộ tham chiếu, hoặc từng model) khớp **đủ 5 số chính VÀ số đặc biệt**, `run_pipeline.notify_perfect_wins()` gửi 1 thông báo ntfy ưu tiên cao nhất (priority `max`), liệt kê model nào trúng + bộ số. Báo **đúng 1 lần** cho mỗi kỳ (chạy trên các kỳ vừa được resolve trả về). Thông báo kèm lưu ý trung thực: đây là trùng khớp may rủi, **không** phải bằng chứng model biết dự đoán — xác suất mỗi bộ vẫn 1/324.632.

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
3. Workflow `predict.yml` tự chạy 2 lần/ngày, ~2 tiếng sau mỗi kỳ quay (15:00 & 23:00 giờ VN). Chạy tay: **Actions → Run workflow**.
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
