package vn.lotto535.watcher.data

/**
 * Nguồn dữ liệu — CHỈ TRANG CHÍNH THỨC.
 *
 * WAF của vietlott.vn chặn IP datacenter, nên GitHub Actions luôn nhận 403 và
 * pipeline trên server phải sống bằng nguồn bên thứ ba. Điện thoại chạy IP dân
 * cư, loại IP mà WAF cho qua — đó là lý do app đọc thẳng nguồn gốc được.
 *
 * Không còn nhánh dự phòng GitHub Pages. Đổi lại: MẤT lớp đối chiếu chéo, nên
 * DrawParser buộc phải khắt khe — không chắc thì trả null, app hiện "không đọc
 * được dãy số" chứ tuyệt đối không hiện số đoán.
 */
object Sources {

    /** Trang chính thức — nguồn duy nhất theo mặc định. */
    val OFFICIAL = listOf(
        "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/535",
        "https://vietlott.vn/vi/choi/lotto535/gioi-thieu-san-pham-535",
    )

    /**
     * Nguồn dự phòng, MẶC ĐỊNH TẮT. Chỉ bật khi mạng của bạn không vào được
     * vietlott.vn — bật trong app, không phải sửa code.
     */
    val MIRRORS = listOf(
        "https://xosominhngoc.net.vn/kqxs-lotto-535",
        "https://www.minhchinh.com/xo-so-dien-toan-lotto-535.html",
    )

    /**
     * Nguồn VÁ LỖ HỔNG — không phải nguồn chính, không bao giờ dùng cho kỳ mới
     * hay giá trị Độc Đắc. Chỉ gọi khi app phát hiện thiếu kỳ trong lịch sử
     * (máy mất mạng nhiều ngày, trang chính thức chỉ đăng kỳ gần nhất).
     * Chứa trọn bộ lịch sử do pipeline công bố.
     */
    const val PAGES_HISTORY = "https://thuantn005.github.io/v5/history.json"

    /**
     * Bảng SỐ NGƯỜI TRÚNG mỗi bậc giải — dữ liệu đo thiên lệch đám đông.
     * minhchinh.com là bên thứ ba, KHÔNG sau WAF vietlott, nên đọc được cả từ
     * điện thoại lẫn CI (đã dò xác nhận). Trang trực tiếp có bảng đầy đủ.
     */
    val WINNER_COUNT_SOURCES = listOf(
        "https://www.minhchinh.com/truc-tiep-xo-so-tu-chon-lotto-535.html",
        "https://www.minhchinh.com/xo-so-dien-toan-lotto-535.html",
    )

    const val USER_AGENT =
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/131.0.0.0 Mobile Safari/537.36"
    const val ACCEPT_LANGUAGE = "vi-VN,vi;q=0.9"
}
