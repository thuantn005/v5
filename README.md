# Vietlott Lotto 5/35 – Dự đoán bằng Claude AI, Auto Notify & Dashboard

Tự động lấy dữ liệu, gọi **Claude (AI mạnh nhất của Anthropic)** để chọn số mỗi kỳ, phát hiện kỳ "chia giải Độc Đắc" và tạo nhiều bộ số cho kỳ đó, gửi thông báo qua [ntfy](https://ntfy.sh), và xuất **Dashboard** trên GitHub Pages với kết quả THẬT đã đối chiếu.

## ⚠️ Đọc trước khi dùng

Lotto 5/35 là trò chơi hoàn toàn ngẫu nhiên — mỗi kỳ quay độc lập, mọi bộ số có xác suất bằng nhau bất kể lịch sử trước đó. **Xác suất trúng Jackpot luôn cố định ở mức 1/324.632, bất kể chọn số theo cách nào.** Không có model, AI, hay LLM nào — kể cả Claude — làm thay đổi được điều đó. Dự án này gọi Claude để chọn số theo yêu cầu của người dùng, không phải vì việc đó có giá trị dự đoán thật; xem `scripts/claude_predict.py` để biết prompt gửi cho Claude, trong đó luôn nhắc lại sự thật này.

Bảng "Độ chính xác thực tế của Claude" trên dashboard dùng đúng các dự đoán thật đã gửi và đối chiếu với kết quả thật — không phải backtest giả lập (khác với hệ thống cũ), vì việc "chạy lại" một LLM qua hàng trăm kỳ quá khứ không khả thi về chi phí.

Dùng dự án này để giải trí và tự động hóa — không nên dùng để đưa ra quyết định tài chính.

## Cấu trúc

```
scripts/
  model.py                    # Draw parsing + đếm số khớp (match_count)
  claude_predict.py            # Gọi Claude API để chọn số (1 hoặc nhiều bộ, có thể loại trừ số)
  jackpot_hunter.py             # Chế độ "Jackpot Hunter": nhiều bộ số né công cụ tham khảo công khai
  multi_log.py                 # Log JSONL mọi dự đoán (Claude + hunter_sets) + đối chiếu kết quả thật
  jackpot_check.py             # Xác định đúng kỳ "chia giải" Độc Đắc (21h ngày kế tiếp, jackpot > 12 tỷ)
  jackpot_watch.py             # "Săn kỳ chia giải": báo SỚM 1 lần ngay khi jackpot vừa vượt 12 tỷ
  notify_ntfy.py                # Gửi push notification qua ntfy.sh
  fetch_data.py                 # Tải CSV kết quả mới nhất
  run_pipeline.py               # Điều phối toàn bộ: Claude predict -> jackpot check -> notify -> log
  generate_dashboard_data.py    # Tổng hợp docs/data.json cho Dashboard

data/all.csv                    # Dữ liệu lịch sử (tự cập nhật)
state/
  ensemble_log.jsonl            # Lịch sử mọi dự đoán (Claude + hunter_sets) + kết quả thật đối chiếu
  jackpot_state.json             # Trạng thái chu kỳ jackpot (chống spam báo sớm)
docs/
  index.html                     # Dashboard (GitHub Pages)
  data.json                      # Dữ liệu cho dashboard (tự sinh mỗi lần chạy)
.github/workflows/predict.yml    # Lịch chạy tự động 2 lần/ngày
```

## Dự đoán bằng Claude

`claude_predict.py::claude_pick(history, n_sets, exclude_main, exclude_special)` gọi thẳng Claude Messages API (`requests.post` tới `api.anthropic.com`, không thêm SDK mới) với model **`claude-opus-4-8`** (bản mạnh nhất hiện có). Prompt gồm:
- Tóm tắt thống kê ngắn (tần suất 50/200 kỳ gần nhất, số "gan" lâu chưa về) — chỉ mang tính tham khảo/"câu chuyện", không phải input có giá trị dự đoán thật.
- System prompt nhắc lại rõ ràng: đây là trò chơi ngẫu nhiên, không có mô hình/AI nào tăng được xác suất trúng thật.
- Yêu cầu trả về đúng JSON (không markdown), có validate chặt (5 số phân biệt 1-35, 1 số đặc biệt 1-12) trước khi dùng; nếu lỗi/timeout thì thử lại tối đa 2 lần rồi bỏ qua lượt đó thay vì đoán bừa.

Nếu thiếu `ANTHROPIC_API_KEY` hoặc API lỗi liên tục: pipeline vẫn chạy các bước jackpot (không phụ thuộc Claude), chỉ bỏ qua phần thông báo dự đoán số của lượt đó.

## 🏹 Chế độ "Jackpot Hunter" — nhiều bộ số cho kỳ chia giải

`jackpot_hunter.py` — dành cho người thật sự muốn tối ưu theo góc nhìn "săn Jackpot" chứ không phải "tăng tỷ lệ trúng" (2 việc khác nhau hoàn toàn):

- **Sự thật duy nhất có ý nghĩa kinh tế thật**: Vietlott chia đều giải Độc Đắc nếu nhiều vé cùng trúng trong 1 kỳ (pari-mutuel). Nếu nhiều người dùng chung 1 công cụ dự đoán công khai (như nhanaz-data) và cùng trúng, họ phải chia nhau giải thưởng.
- Script tự tải **sổ dự đoán đã khóa trước, có hash chain chống sửa** của `nhanaz-data/vietlott-prediction-web` (`predictions/ledger.jsonl`) — không đoán mò, dùng đúng số họ đã công bố công khai cho kỳ tới.
- Vào đúng kỳ chia giải Độc Đắc, gọi Claude yêu cầu **5 bộ số đa dạng** (`N_HUNTER_SETS`), **loại trừ hoàn toàn** mọi số nằm trong dự đoán công khai đó — cho người dùng nhiều lựa chọn vé để mua, đều né rủi ro chia giải với công cụ tham khảo.
- Nếu không tải được sổ dự đoán tham khảo (mạng lỗi, repo đổi cấu trúc), tự động dùng Claude không loại trừ gì và báo rõ `reference_available: false` — không đoán bừa.
- Các bộ số Hunter chỉ được tạo vào đúng kỳ chia giải Độc Đắc (không phải mỗi lượt chạy), xuất hiện riêng trong thông báo ntfy và trong dashboard.

**Nhắc lại**: các bộ Hunter không có xác suất trúng cao hơn bộ Claude chính hay bất kỳ bộ nào khác — chúng chỉ khác về mặt "nếu trúng thì đỡ phải chia" (giả định người khác dùng chung công cụ tham khảo và cùng trúng).

## Vì sao workflow đôi khi không chạy đúng giờ đã đặt (và cách đã khắc phục)

GitHub Actions chạy `schedule` theo kiểu **best-effort**, không đảm bảo đúng giờ tuyệt đối — đặc biệt hay bị trễ hoặc bỏ lỡ nếu đặt vào **đúng phút 00** của giờ, vì đó là lúc hàng loạt workflow khác trên toàn GitHub cùng kích hoạt, gây nghẽn hàng đợi (giới hạn nền tảng, GitHub công bố công khai). Đã khắc phục bằng 2 cách:

1. **Đổi giờ chạy sang phút lẻ** (14:07 & 22:12 giờ VN thay vì đúng 14:00/22:00) — né giờ cao điểm.
2. **Thêm lượt chạy dự phòng** 30 phút sau mỗi lượt chính (14:37 & 22:42) — nếu lượt chính bị GitHub bỏ lỡ, lượt dự phòng sẽ chạy thay. `run_pipeline.py` có cơ chế chống trùng (`already_predicted()`): nếu đã dự đoán cho kỳ đó rồi (lượt chính chạy thành công), lượt dự phòng sẽ tự bỏ qua, không gửi thông báo hay ghi log trùng lặp.

## Quy tắc "kỳ chia giải Độc Đắc"

Theo quy định Vietlott: khi giải Độc Đắc vượt 12 tỷ đồng mà chưa ai trúng, kỳ quay 21h00 của **ngày kế tiếp** (không phải kỳ quay ngay sau đó nếu cùng ngày) mới là kỳ chia giải. `jackpot_check.py` chỉ báo `is_sharing_round=True` khi (a) jackpot > 12 tỷ, VÀ (b) kỳ sắp dự đoán đúng là kỳ 21h của ngày kế tiếp.

Có 2 tầng thông báo:
1. **Báo sớm** (`jackpot_watch.py`): ngay khi jackpot vừa vượt 12 tỷ lần đầu trong chu kỳ.
2. **Báo đúng ngày**: khi đến chính xác kỳ 21h ngày chia giải, kèm bộ số Claude + nhiều bộ số Jackpot Hunter.

## Dashboard (GitHub Pages)

`docs/index.html` đọc `docs/data.json` (tự sinh mỗi lần workflow chạy) và hiển thị:
- 🎯 Bộ số dự đoán mới nhất (Claude + các bộ Jackpot Hunter khi có)
- 📈 Biểu đồ hiệu năng theo thời gian (trung bình khớp lũy kế thật của Claude)
- 📊 Lịch sử các kỳ quay và kết quả thật
- 📉 Độ chính xác thực tế của Claude (từ các kỳ đã triển khai thật, không phải backtest lịch sử)

**Kích hoạt GitHub Pages** (1 lần): repo → Settings → Pages → Source: **Deploy from a branch** → Branch: `main`, folder **`/docs`** → Save. Sau đó dashboard sẽ có ở `https://<username>.github.io/<repo>/`.

## Nguồn dữ liệu

Mặc định lấy từ dataset công khai [`NhanAZ-Data/vietlott-data-research`](https://github.com/NhanAZ-Data/vietlott-data-research). Đổi `SOURCE_URL` trong `fetch_data.py` nếu muốn dùng nguồn khác (chỉ cần cột `draw_id` và `result_json` cùng định dạng).

## Thiết lập trên GitHub

1. Tạo repo mới, upload toàn bộ nội dung thư mục này.
2. Tab **Actions** → bật workflow nếu được hỏi.
3. Tạo secret cho Claude API: repo → **Settings → Secrets and variables → Actions → New repository secret** → tên `ANTHROPIC_API_KEY`, giá trị là API key Anthropic của bạn. **Thiếu secret này thì mọi lượt chạy sẽ bỏ qua bước dự đoán số** (chỉ còn báo jackpot hoạt động).
4. Workflow `predict.yml` tự chạy 2 lần/ngày (14:00 & 22:00 giờ VN). Chạy tay: **Actions → Run workflow**.
5. (Tuỳ chọn) Bật **GitHub Pages** như hướng dẫn ở trên để có dashboard.
6. Cài app **ntfy**, subscribe topic `lotto535-thuan`.

**Lưu ý chi phí**: mỗi lượt chạy hợp lệ (không bị dedup bởi lượt dự phòng) gọi Claude API 1 lần (dự đoán chính) + 1 lần nữa (5 bộ số Hunter) vào đúng kỳ chia giải — khoảng 2 lần/ngày, tính phí theo tài khoản Anthropic của bạn.

## Chạy thử ở máy local

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key-here
python scripts/fetch_data.py
python scripts/run_pipeline.py
python scripts/generate_dashboard_data.py
```

Lần chạy đầu tiên sẽ tự tạo file `state/ensemble_log.jsonl` vì chưa có gì tồn tại.

## Tùy chỉnh

- `claude_predict.py`: đổi `MODEL` để dùng model Claude khác (mặc định `claude-opus-4-8`, mạnh nhất hiện có). Sửa `_build_prompt()` để đổi cách cung cấp ngữ cảnh thống kê hoặc yêu cầu gửi Claude.
- `jackpot_hunter.py`: đổi `N_HUNTER_SETS` để tăng/giảm số lượng vé gợi ý cho kỳ chia giải.
- `jackpot_check.py`: mang tính "best-effort" — nếu Vietlott đổi cấu trúc trang, script im lặng bỏ qua thay vì đoán bừa.
