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

## Thứ tự nguồn

1. `vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/535` — chính thức
2. `vietlott.vn/vi/choi/lotto535/gioi-thieu-san-pham-535` — chính thức
3. `xosominhngoc.net.vn` — dự phòng đã kiểm chứng
4. `minhchinh.com` — dự phòng đã kiểm chứng
5. `thuantn005.github.io/v5/jackpot.json` — dữ liệu repo tự công bố, chốt cuối

## Độ tin cậy của hai bộ parser — khác nhau

**Parser Độc Đắc** (`JackpotParser.kt`) là bản cổng **nguyên văn** từ
`scripts/jackpot_check.py::_extract_jackpot` — cùng nhãn, cùng danh sách decoy
("ước tính", "kỳ tới", "doanh thu"…), cùng cửa sổ 200 ký tự, cùng lớp kiểm định
theo mã kỳ. Bản Python đó đã chạy thật nhiều tháng. Đáng tin.

**Parser kết quả số** (`DrawParser.kt`) thì KHÔNG — và nó ĐÃ hiện sai số thật.
Trang kết quả xếp "Kỳ #00812" rồi tới ngày "09/08/2026" rồi mới tới dãy số, nên
regex nuốt luôn `09` và `08` thành hai số xổ số: kỳ #00812 hiện ra
`03 08 09 12 19` thay vì `03 12 19 29 30`.

Đã sửa hai lớp:

1. `stripNoise()` xoá ngày/giờ/tiền/mã kỳ khỏi vùng dò trước khi tìm số, thay
   bằng khoảng trắng cùng độ dài để vị trí không xê dịch. Thêm kiểm tra 5 quả
   bóng phải nằm sát nhau (≤200 ký tự), quá xa thì trả `null`.
2. **Đảo thứ tự nguồn cho dãy số**: `data.json` của pipeline (đã kiểm định chéo)
   là nguồn CHÍNH, HTML cào chỉ để đối chiếu. Hai bên lệch nhau thì tin
   `data.json` và ghi xung đột vào danh sách lỗi hiển thị trong app.

Nhãn nguồn trong app cho biết đang chạy nhánh nào:

| Nhãn | Nghĩa |
|---|---|
| `vietlott.vn + github pages (khớp)` | hai nguồn độc lập cho cùng kết quả — chắc nhất |
| `github pages` | chỉ có nguồn đã kiểm định; cào HTML không ra số |
| `vietlott.vn (chưa đối chiếu)` | kỳ mới hơn pages chưa kịp công bố |
| dòng `LỆCH kỳ #…` ở mục lỗi | hai nguồn bất đồng; app hiện số của pages |

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
