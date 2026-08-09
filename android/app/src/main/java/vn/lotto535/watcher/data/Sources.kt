package vn.lotto535.watcher.data

/**
 * Nguồn dữ liệu, xếp theo THỨ TỰ ƯU TIÊN.
 *
 * Điểm mấu chốt của app này: WAF của vietlott.vn CHẶN IP datacenter, nên
 * GitHub Actions luôn nhận HTTP 403 khi gọi trang chính thức — pipeline trên
 * server buộc phải dựa vào nguồn bên thứ ba. Điện thoại chạy bằng IP dân cư
 * (4G/5G/Wi-Fi nhà), là loại IP mà WAF cho qua. Vì vậy app đứng trên máy bạn
 * mới có cửa đọc THẲNG trang chính thức — đó là lý do tồn tại của nó.
 */
object Sources {

    /** Trang chính thức — ưu tiên tuyệt đối. */
    val OFFICIAL = listOf(
        "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/535",
        "https://vietlott.vn/vi/choi/lotto535/gioi-thieu-san-pham-535",
    )

    /** Dự phòng — chỉ dùng khi trang chính thức không truy cập được. */
    val MIRRORS = listOf(
        "https://xosominhngoc.net.vn/kqxs-lotto-535",
        "https://www.minhchinh.com/xo-so-dien-toan-lotto-535.html",
    )

    /**
     * Dự phòng cuối: dữ liệu do chính pipeline của repo công bố lên GitHub
     * Pages. Không phải nguồn gốc, nhưng đã qua kiểm định chéo nhiều nguồn.
     */
    const val PAGES_DATA = "https://thuantn005.github.io/v5/data.json"
    const val PAGES_JACKPOT = "https://thuantn005.github.io/v5/jackpot.json"

    const val USER_AGENT =
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/131.0.0.0 Mobile Safari/537.36"
    const val ACCEPT_LANGUAGE = "vi-VN,vi;q=0.9"
}
