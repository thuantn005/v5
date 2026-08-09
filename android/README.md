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

**Parser kết quả số** (`DrawParser.kt`) thì **chưa** được đối chiếu với HTML
thật của vietlott.vn — môi trường viết app trả 403 với trang đó nên không kiểm
chứng được tại chỗ. Vì vậy nó được viết theo hướng **thà không trả gì còn hơn
đoán bừa**: không đủ chắc thì trả `null` và app lùi xuống `data.json` trên
GitHub Pages (đã qua kiểm định chéo của pipeline). Nếu bạn thấy app hiện đúng
pot nhưng dãy số lấy từ "github pages" thay vì "vietlott.vn", thì đó chính là
nhánh dự phòng đang chạy — gửi tôi HTML thật của trang để chỉnh parser.

## Chu kỳ chạy nền

WorkManager, mặc định **30 phút/lần** (tối thiểu hệ thống cho phép là 15).
Đủ dày, vì cảnh báo chia giải tính theo **ngày** chứ không theo phút.

Chọn WorkManager thay vì AlarmManager vì nó sống sót qua khởi động lại máy, tự
hoãn khi mất mạng, và tuân thủ Doze thay vì bị hệ thống giết.

**Quan trọng:** trên Xiaomi/Oppo/Vivo/Samsung, tối ưu hoá pin hay bóp chết
công việc nền. App có nút **"Tắt tối ưu pin cho app"** đưa thẳng tới màn hình
cài đặt tương ứng — nên bấm ngay sau khi cài.

## Build tại máy

```bash
cd android
gradle assembleDebug        # cần Android SDK + JDK 17
```
