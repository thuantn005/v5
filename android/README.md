# Lotto 5/35 — App báo kỳ CHIA GIẢI

App Android tự cào **trang chính thức vietlott.vn** ngay trên điện thoại và
đẩy thông báo khi có kỳ **Chia Giải Độc Đắc**.

## Vì sao phải là app trên điện thoại

WAF của vietlott.vn **chặn IP datacenter**. Pipeline chạy trên GitHub Actions
gần như luôn nhận HTTP 403 với trang chính thức, nên buộc phải sống bằng nguồn
bên thứ ba (xosominhngoc, minhchinh). Điện thoại chạy bằng **IP dân cư** —
đúng loại IP mà WAF cho qua. Vì vậy app đứng trên máy bạn mới có cửa đọc thẳng
nguồn gốc, việc mà server không làm được.

## Cách lấy APK

1. Vào tab **Actions** của repo → workflow **Build APK Android** → **Run workflow**
2. Chờ build xong (~3–5 phút)
3. Mở lần chạy đó, kéo xuống mục **Artifacts**, tải `lotto535-apk`
4. Giải nén, chép `app-release.apk` sang điện thoại
5. Mở file, cho phép **"Cài đặt từ nguồn không xác định"**

APK ký bằng khoá debug — cài trực tiếp được, nhưng không đăng Play Store được.

## Quy tắc kỳ chia giải

Cổng nguyên văn từ `scripts/jackpot_watch.py`:

> Kết thúc một kỳ quay bất kỳ, nếu Độc Đắc **vượt 12 tỷ** mà không có người
> trúng, thì kỳ quay **cuối cùng (21:00)** của **ngày liền kế tiếp** là kỳ
> **Chia Giải Độc Đắc**.

Máy trạng thái theo dõi bốn chuyển tiếp:

| Trạng thái | Khi nào | Mặc định báo |
|---|---|---|
| `scheduled` | pot vượt 12 tỷ → đã xác định ngày chia giải | ✅ |
| `reminder` | hôm nay chính là ngày chia giải | ✅ (ưu tiên tối đa) |
| `cancelled` | có người trúng trước kỳ chia giải | ❌ |
| `completed` | kỳ chia giải đã diễn ra, pot reset | ❌ |
| `new_draw` | có kết quả kỳ mới | ❌ |
| `scrape_fail` | mọi nguồn đều lỗi | ❌ |

Bật/tắt từng loại trong app. Mọi mốc ngày giờ tính theo **giờ VN (UTC+7)**,
không theo giờ máy — mang điện thoại ra nước ngoài vẫn báo đúng ngày ở VN.

## Nguồn — CHỈ trang chính thức

1. `vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/535`
2. `vietlott.vn/vi/choi/lotto535/gioi-thieu-san-pham-535`

Không còn nhánh GitHub Pages. `xosominhngoc` và `minhchinh` vẫn nằm trong code
nhưng **mặc định TẮT** — bật bằng công tắc "Dùng nguồn dự phòng" trong app nếu
mạng của bạn không vào được vietlott.vn.

Hệ quả phải chấp nhận: không còn nguồn thứ hai để đối chiếu chéo. Bù lại,
`DrawParser` được siết để **thà trả null còn hơn trả số sai** — không đọc chắc
chắn được thì app hiện "⚠️ Không đọc được dãy số từ trang chính thức".

## Độ tin cậy của hai bộ parser — khác nhau

**Parser Độc Đắc** (`JackpotParser.kt`) là bản cổng **nguyên văn** từ
`scripts/jackpot_check.py::_extract_jackpot` — cùng nhãn, cùng danh sách decoy
("ước tính", "kỳ tới", "doanh thu"…), cùng cửa sổ 200 ký tự, cùng lớp kiểm định
theo mã kỳ. Bản Python đó đã chạy thật nhiều tháng. Đáng tin.

**Parser kết quả số** (`DrawParser.kt`) giờ đã đối chiếu với HTML THẬT. Định
dạng thật của vietlott.vn là:

    Kỳ quay thưởng #00814 ngày 09/08/2026
    0116192933|01

Năm số chính **dính liền thành 10 chữ số**, rồi dấu `|`, rồi số đặc biệt. Hai
bản trước đều sai vì không biết điều này:

* bản đầu dò từng số hai chữ số → nuốt ngày `09/08/2026` thành số xổ số, kỳ
  #00812 hiện ra `03 08 09 12 19` thay vì `03 12 19 29 30`
* bản thứ hai xoá được ngày nhưng vẫn dò theo ranh giới từ, mà `0116192933`
  là một khối liền → chỉ tìm được 2 số, luôn trả null

Bản hiện tại bám dấu `|` làm mốc neo — không còn phải đoán ranh giới con số, và
ngày tháng phía trên không thể lọt vào. Đối chiếu với `data/all.csv` kỳ #00814:
`[1, 16, 19, 29, 33]` + ĐB `1` — khớp.

Đã sửa hai lớp:

1. `stripNoise()` xoá ngày/giờ/tiền/mã kỳ khỏi vùng dò trước khi tìm số, thay
   bằng khoảng trắng cùng độ dài để vị trí không xê dịch. Thêm kiểm tra 5 quả
   bóng phải nằm sát nhau (≤200 ký tự), quá xa thì trả `null`.
2. **Đảo thứ tự nguồn cho dãy số**: `data.json` của pipeline (đã kiểm định chéo)
   là nguồn CHÍNH, HTML cào chỉ để đối chiếu. Hai bên lệch nhau thì tin
   `data.json` và ghi xung đột vào danh sách lỗi hiển thị trong app.

Kiểm tra: 6 ca đều đạt — HTML thật, dạng `|` có khoảng trắng, dạng token cũ có
ngày xen giữa, và ba ca phải trả null (số trùng nhau, số ngoài 1..35, ĐB ngoài
1..12).

## Mất mạng đúng khung giờ thì sao

Mốc đó **không bị bỏ**. Mọi yêu cầu mang ràng buộc `NetworkType.CONNECTED`, nên
WorkManager giữ việc ở trạng thái chờ và chạy ngay khi mạng trở lại — dù ba
tiếng sau. Cào lỗi giữa chừng thì `Result.retry()` lùi dần theo cấp số nhân,
vẫn kèm đúng ràng buộc ấy.

Ba lớp bảo đảm một mốc không mất:

1. **Ràng buộc mạng** — hoãn chứ không bỏ.
2. **KEEP khi mở app.** Trước đây `ensureScheduled` luôn dùng `REPLACE`: mở app
   lúc 15:00 trong khi mốc 13:10 đang treo chờ mạng sẽ **xoá mất** nó và hẹn
   sang 21:10, kỳ trưa không bao giờ được kiểm tra. Giờ mở app / khởi động máy
   dùng `KEEP`, chỉ cuối mỗi lần chạy mới `REPLACE` để nối chuỗi.
3. **Lưới an toàn 6 giờ** — hồi sinh chuỗi nếu ROM cắt mất.

## Lịch cào — bám mốc giờ, không quét đều

Lotto 5/35 chỉ quay **13:00** và **21:00**, nên quét đều cả ngày là lãng phí.
App chỉ cào ở ba mốc (giờ VN):

| Mốc | Mục đích |
|---|---|
| **08:00** | nhắc "HÔM NAY là kỳ chia giải" từ sáng, còn kịp mua vé |
| **13:10** | ngay sau kỳ quay trưa |
| **21:10** | ngay sau kỳ quay tối |

Ở hai mốc quay, nếu kỳ mới chưa về (trang hay cập nhật trễ) thì hẹn thử lại sau
**25 phút, tối đa 2 lần**. Kỳ đã về thì không thử lại.

    ngày bình thường : 3 lần
    ngày xấu nhất    : 7 lần

Mỗi lần cào gửi **1-6 request** tuỳ nguồn nào trả lời trước — dừng ngay khi đủ.

**Có mạng mới chạy.** Mọi yêu cầu mang ràng buộc `NetworkType.CONNECTED`: mất
mạng thì WorkManager *giữ lại* và chạy ngay khi mạng trở lại, không bỏ lỡ mốc.
Cào lỗi thì `Result.retry()` cho lùi dần theo cấp số nhân, vẫn kèm ràng buộc đó.

Chuỗi tự nối: mỗi lần chạy xong lại hẹn mốc kế tiếp. Thêm lưới an toàn 6 giờ/lần
để vớt trường hợp ROM cắt chuỗi — nó tự bỏ qua nếu vừa cào thành công trong 4
giờ qua, nên gần như không tốn gì.

Chọn WorkManager thay vì AlarmManager vì nó sống sót qua khởi động lại máy, tự
hoãn khi mất mạng, và tuân thủ Doze thay vì bị hệ thống giết. Đổi lại giờ chạy
có thể lệch ~10-15 phút khi máy nằm im — chấp nhận được, vì cảnh báo chia giải
tính theo **ngày**.

**Quan trọng:** trên Xiaomi/Oppo/Vivo/Samsung, tối ưu hoá pin hay bóp chết
công việc nền. App có nút **"Tắt tối ưu pin cho app"** đưa thẳng tới màn hình
cài đặt tương ứng — nên bấm ngay sau khi cài.

## Build tại máy

```bash
cd android
gradle assembleDebug        # cần Android SDK + JDK 17
```
