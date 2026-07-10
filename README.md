# Vietlott Lotto 5/35 – "3 vé mỗi kỳ" + Theo dõi trung thực

Mỗi kỳ quay, hệ thống tự động xuất **2 vé** — 1 vé Neural Perceptron và 1 mốc ngẫu
nhiên công bằng — gửi qua [ntfy](https://ntfy.sh), đối chiếu với kết quả thật và
hiển thị trên **Dashboard** (GitHub Pages). Không cách chọn số nào vượt được may
rủi; các vé chỉ để theo dõi/minh hoạ điều đó một cách trung thực.

## ⚠️ Đọc trước khi dùng

Lotto 5/35 hoàn toàn ngẫu nhiên — mỗi kỳ độc lập, mọi bộ số có xác suất bằng nhau.
**Xác suất trúng Jackpot luôn cố định 1/324.632, bất kể chọn số cách nào.** Dự án
này **không** làm tăng cơ hội trúng; dùng để giải trí và học thống kê, không dùng
để ra quyết định tài chính. "Mốc so sánh công bằng" (vé ngẫu nhiên) là chuẩn để
thấy rõ: 3 vé đều bám quanh kỳ vọng ngẫu nhiên, không cái nào "giỏi" hơn.

## Các vé mỗi kỳ

| Vé | Ý nghĩa |
|---|---|
| **Mạng nơ-ron** (`ticket_neural`, `ensemble.py`) | Ma trận trọng số W[output][input] học từ 100 kỳ gần nhất: P(số xuất hiện tiếp \| số vừa ra). Score = 0.7·W·x + 0.3·prior. Backtest walk-forward avg_hits=0.7565 (baseline 0.7143), p=0.1304 (chưa có ý nghĩa thống kê). |
| **Mốc so sánh công bằng** (`random_fair`, `references.py`) | 5 số **khác nhau** chọn ngẫu nhiên đều — *null model đúng*. Mọi vé xác suất như nhau, nên đây là thước đo trung thực để đối chiếu. Kèm mã lưu vết để tái tạo. |

### Mã lưu vết (reproducible)

Hai vé ngẫu nhiên kèm **mã lưu vết** + **công thức công khai** để ai cũng tạo lại
đúng bộ số và kiểm toán rằng số không bị chọn lọc thiên vị. Seed chỉ phụ thuộc mã
kỳ (biết trước), không bao giờ phụ thuộc kết quả:

```
random_fair   : trace = L535-<draw>-FAIR    | seed = int(draw)
                rng = random.Random(seed); main = sorted(rng.sample(range(1,36), 5)); special = rng.randint(1,12)
random_repeat : trace = L535-<draw>-REPEAT  | seed = int(draw) + 1_000_000
                rng = random.Random(seed); main = sorted(rng.randint(1,35) for _ in range(5)); special = rng.randint(1,12)
```

`references.reproduce("L535-00753-FAIR")` tái tạo đúng bộ số của vé đó.

## Cấu trúc

```
scripts/
  model.py                      # Parse dữ liệu kỳ quay + match_count (đếm số khớp)
  strategies.py                 # 3 model active (gap_zscore/momentum/crowd_avoidance) cho vé Ensemble
  ensemble.py                   # Gộp 3 model thành 1 vé Ensemble (nhóm tương quan + trọng số p-value)
  references.py                 # Tạo 3 vé so sánh + mã lưu vết; fetch đồng thuận nhanaz-data
  run_pipeline.py               # Điều phối: tạo 4 vé -> thông báo -> log -> đối chiếu
  multi_log.py                  # Log JSONL 3 vé mỗi kỳ + đối chiếu kết quả thật
  jackpot_check.py              # Xác định đúng kỳ "chia giải" Độc Đắc (jackpot > 12 tỷ)
  jackpot_watch.py              # Báo sớm khi jackpot vượt 12 tỷ + báo "mù" khi scrape lỗi
  notify_ntfy.py                # Gửi push notification qua ntfy.sh
  fetch_data.py                 # Cào kết quả kỳ quay trực tiếp từ web (minhchinh.com + vietlott.vn)
  generate_dashboard_data.py    # Tổng hợp docs/data.json cho Dashboard

data/all.csv                    # Dữ liệu lịch sử (tự cập nhật)
state/
  ensemble_log.jsonl            # Lịch sử 3 vé mỗi kỳ + kết quả thật đối chiếu
  jackpot_state.json            # Trạng thái chu kỳ jackpot (chống spam báo sớm)
docs/index.html + data.json     # Dashboard (GitHub Pages)
.github/workflows/predict.yml   # Lịch chạy tự động 2 lần/ngày (~2h sau mỗi kỳ quay)
```

## Thông báo ntfy

Mỗi kỳ gửi **1 tin "3 vé kỳ tới"** (priority cao ở kỳ chia giải). Ngoài ra:

- **Báo sớm** khi jackpot vừa vượt 12 tỷ (1 lần/chu kỳ).
- **Báo "mù"** (`jackpot_watch.check_scrape_alert`): khi **mọi nguồn tra cứu
  jackpot đều lỗi**, gửi 1 cảnh báo để kiểm tra thủ công, tránh im lặng bỏ lỡ kỳ
  chia giải. Tự tắt khi tra cứu hoạt động lại.
- **Báo TRÚNG** (`run_pipeline.notify_perfect_wins`): khi đối chiếu kết quả, nếu
  **bất kỳ vé nào** khớp đủ **5 số chính + đặc biệt**, gửi tin priority cao nhất
  (đúng 1 lần/kỳ). Kèm lưu ý trung thực: trùng khớp là may rủi, không phải kỹ năng.

Mọi lời gọi ntfy là *best-effort* — lỗi mạng/ntfy không làm hỏng pipeline (vẫn log
và đối chiếu bình thường).

## Quy tắc "kỳ chia giải Độc Đắc"

Theo Vietlott: khi Độc Đắc vượt 12 tỷ mà chưa ai trúng, kỳ quay 21h00 của **ngày
kế tiếp** mới là kỳ chia giải. `jackpot_check.py` chỉ báo `is_sharing_round=True`
khi (a) jackpot > 12 tỷ VÀ (b) kỳ sắp tới đúng là kỳ 21h ngày kế tiếp. Kỳ chia giải
là lúc quỹ Độc Đắc được phân bổ xuống các giải thấp hơn ngay cả khi không ai khớp
5/5 — điều thật duy nhất làm kỳ vọng kỳ đó cao hơn, **không** liên quan tới việc
chọn số nào.

## Lịch chạy & độ tin cậy

GitHub Actions chạy `schedule` **best-effort** (quan sát được có lúc trễ ~5 tiếng).
Lịch: **~2 tiếng sau mỗi kỳ quay** (15:00 & 23:00 giờ VN, cron ở phút :07 primary
và :27 backup để tránh nghẽn phút :00). Pipeline idempotent theo từng kỳ
(`already_predicted()` / `resolve_all()`) nên chạy trễ/dư/bỏ lỡ 1 lượt đều vô hại.
Lịch chỉ chạy từ nhánh mặc định (`main`) và bị GitHub tự tắt sau 60 ngày không
commit — bước tự commit hằng ngày giữ lịch luôn sống.

## Dashboard (GitHub Pages)

`docs/index.html` đọc `docs/data.json` và hiển thị:
- 🎫 **3 vé mới nhất** (kèm mã lưu vết + công thức tái lập)
- 📉 **Tỷ lệ trúng của 3 vé** so với kỳ vọng ngẫu nhiên 0.7143 số/kỳ
- 📈 Biểu đồ tỷ lệ khớp lũy kế theo thời gian của 3 vé
- 📊 Lịch sử các kỳ quay + số khớp của từng vé

**Kích hoạt Pages** (1 lần): Settings → Pages → Deploy from a branch → `main` /
`/docs` → Save.

## Nguồn dữ liệu kết quả kỳ quay

`fetch_data.py` cào trực tiếp từ **2 nguồn độc lập** (không phụ thuộc kho dữ liệu bên thứ ba):

| Nguồn | Phạm vi | Ưu tiên |
|---|---|---|
| `minhchinh.com` | ~15 kỳ gần nhất, có giờ quay | Nguồn chính |
| `vietlott.vn` | Kỳ mới nhất, có mã kỳ chính thức | Bổ sung |

- `data/all.csv` đã có đủ lịch sử đầy đủ (commit vào repo). Script chỉ **bổ sung** kỳ mới (chưa có) — an toàn khi chạy nhiều lần.
- Cả 2 nguồn lỗi → giữ nguyên dữ liệu cũ, không crash.
- **Giá trị Jackpot** (`jackpot_check.py`): 5 nguồn dự phòng; tất cả lỗi → `jackpot_vnd: null`, không đoán bừa.

## Chạy thử local

```bash
pip install -r requirements.txt
python scripts/fetch_data.py
python scripts/run_pipeline.py
python scripts/generate_dashboard_data.py
python scripts/references.py        # in thử 3 vé + chứng minh mã lưu vết tái lập
```

## Thiết lập trên GitHub

1. Upload repo. Tab **Actions** → bật workflow.
2. `predict.yml` tự chạy 2 lần/ngày (~15:00 & 23:00 giờ VN). Chạy tay: **Actions → Run workflow**.
3. (Tuỳ chọn) Bật **GitHub Pages** cho dashboard.
4. Cài app **ntfy**, subscribe topic `lotto535-thuan`.
