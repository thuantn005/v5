package vn.lotto535.watcher.data

/** Một kỳ quay Lotto 5/35. */
data class Draw(
    val drawId: String,
    val drawDate: String,      // yyyy-MM-dd
    val numbers: List<Int>,    // 5 số chính 1..35
    val special: Int?,         // 1 số đặc biệt 1..12
) {
    fun pretty(): String {
        val main = numbers.joinToString(" ") { String.format("%02d", it) }
        return if (special != null) "$main + ĐB ${String.format("%02d", special)}" else main
    }
}

/**
 * Bóc kỳ quay ra khỏi HTML trang kết quả.
 *
 * LƯU Ý TRUNG THỰC: bộ nhận dạng này CHƯA từng chạy với HTML thật của
 * vietlott.vn — môi trường build trả 403 với trang đó. Bản đầu đã đọc SAI:
 * trang xếp "Kỳ #00812" rồi ngày "09/08/2026" rồi mới tới dãy số, nên nó nuốt
 * `09` và `08` thành số xổ số.
 *
 * Từ khi bỏ nguồn GitHub Pages, KHÔNG còn gì đối chiếu nữa. Nên mọi điều kiện
 * dưới đây đều theo hướng THÀ TRẢ NULL:
 *
 *   - xoá ngày/giờ/tiền/mã kỳ trước khi dò số
 *   - 5 số phải phân biệt và nằm trong 1..35
 *   - 5 số phải sát nhau (≤200 ký tự), rải xa hơn nghĩa là vơ từ nhiều khối
 *   - BẮT BUỘC có số đặc biệt 1..12; thiếu là dấu hiệu đọc nhầm khối
 *
 * Trả null thì app hiện "không đọc được dãy số" — thông tin đúng. Trả số sai
 * thì người dùng dò vé theo số bịa. Hai cái đó không cùng hạng.
 */
object DrawParser {

    private val KY = Regex("""#\s*(\d{3,6})""")
    private val DATE = Regex("""(\d{2})[/-](\d{2})[/-](\d{4})""")
    // 5 số 2 chữ số cách nhau bởi thẻ/khoảng trắng, rồi tới số đặc biệt.
    private val BALLS = Regex("""\b(0[1-9]|[12]\d|3[0-5])\b""")

    /**
     * Những thứ TRÔNG như số xổ số nhưng không phải, phải xoá trước khi dò.
     *
     * Ngày tháng là thủ phạm chính: trang kết quả xếp "Kỳ #00812" rồi tới
     * "09/08/2026" rồi mới tới dãy số. Không xoá thì `09` và `08` bị nhận làm
     * hai số đầu và vé hiện ra sai hoàn toàn — đã tái hiện được lỗi này.
     */
    private val NOISE = listOf(
        Regex("""\d{1,4}[/-]\d{1,2}[/-]\d{1,4}"""),   // 09/08/2026, 2026-08-09
        Regex("""\b\d{1,2}\s*[:h]\s*\d{2}\b"""),      // 13:00, 21h00
        Regex("""[\d][\d.,]{8,}"""),                  // 6.648.422.500 (tiền)
        Regex("""#\s*\d{3,6}"""),                      // chính mã kỳ
    )

    private fun stripNoise(s: String): String {
        var out = s
        for (r in NOISE) out = r.replace(out) { m -> " ".repeat(m.value.length) }
        return out
    }

    /** Cắt bỏ thẻ HTML, giữ lại text để dò số cho đỡ nhiễu. */
    private fun stripTags(html: String): String =
        html.replace(Regex("""<script[\s\S]*?</script>""", RegexOption.IGNORE_CASE), " ")
            .replace(Regex("""<style[\s\S]*?</style>""", RegexOption.IGNORE_CASE), " ")
            .replace(Regex("""<[^>]+>"""), " ")
            .replace(Regex("""\s+"""), " ")

    /**
     * Định dạng THẬT của vietlott.vn, đã đối chiếu với trang sống:
     *
     *     Kỳ quay thưởng #00814 ngày 09/08/2026
     *     0116192933|01
     *
     * Năm số chính dính liền thành 10 chữ số, rồi dấu `|`, rồi số đặc biệt.
     * Dấu `|` là mốc neo rất chắc — bám vào nó thì không còn phải đoán ranh
     * giới từng con số, và ngày tháng phía trên không thể lọt vào.
     *
     * Cho phép khoảng trắng xen giữa để phòng trường hợp HTML tách các chữ số
     * ra thẻ riêng (sau stripTags sẽ thành "01 16 19 29 33 | 01").
     */
    private val PIPE_FORM = Regex("""((?:\d\s*){10})\|\s*((?:\d\s*){2})""")

    /**
     * Bóc MỌI kỳ đọc được trên trang, sắp xếp tăng dần theo mã kỳ.
     *
     * Vì sao không chỉ lấy kỳ mới nhất: nếu điện thoại mất mạng suốt từ trưa
     * tới đêm thì CẢ HAI kỳ 13:00 và 21:00 đều đã quay. Chỉ đọc kỳ mới nhất sẽ
     * làm kỳ giữa biến mất không dấu vết. Trang nào liệt kê nhiều kỳ thì ta vớt
     * hết; phần còn thiếu sẽ được báo là lỗ hổng chứ không im lặng bỏ qua.
     */
    fun parseAll(html: String): List<Draw> {
        val text = stripTags(html)
        val out = LinkedHashMap<String, Draw>()
        for (ky in KY.findAll(text)) {
            val drawId = ky.groupValues[1].padStart(5, '0')
            if (out.containsKey(drawId)) continue
            val d = parsePipeForm(text, ky.range.last + 1, drawId)
                ?: parseTokenForm(text, ky.range.last + 1, drawId)
            if (d != null) out[drawId] = d
        }
        return out.values.sortedBy { it.drawId }
    }

    /** Kỳ mới nhất đọc được, hoặc null. */
    fun parseLatest(html: String): Draw? = parseAll(html).lastOrNull()

    /**
     * Dạng cũ: từng số hai chữ số tách rời. Giữ làm phương án dự phòng phòng
     * khi trang đổi cách hiển thị.
     */
    private fun parseTokenForm(text: String, from: Int, drawId: String): Draw? {

        // Chỉ soi trong ~400 ký tự ngay sau mã kỳ: đó là khối kết quả của kỳ đó.
        // stripNoise thay ngày/giờ/tiền bằng khoảng trắng CÙNG ĐỘ DÀI, nên vị
        // trí các ký tự không xê dịch.
        val window = stripNoise(text.substring(from, minOf(text.length, from + 400)))

        val hits = BALLS.findAll(window).take(5).toList()
        if (hits.size < 5) return null
        val main = hits.map { it.value.toInt() }.sorted()
        if (main.distinct().size != 5) return null

        // 5 quả bóng của cùng một kỳ nằm sát nhau. Nếu chúng trải ra quá rộng
        // thì ta đang vơ số từ nhiều khối khác nhau — thà trả null còn hơn.
        if (hits[4].range.last - hits[0].range.first > 200) return null

        // Số đặc biệt 1..12 là số hai chữ số đầu tiên NGAY SAU 5 số chính.
        val afterMain = window.substring(minOf(hits[4].range.last + 1, window.length))
        val special = Regex("""\b(0[1-9]|1[0-2])\b""").find(afterMain)
            ?.value?.toIntOrNull()?.takeIf { it in 1..12 }

        // Không còn nguồn thứ hai để đối chiếu, nên thiếu số đặc biệt là dấu
        // hiệu ta đọc nhầm khối — bỏ luôn, đừng trả về nửa vời.
        if (special == null) return null

        return Draw(drawId, dateOf(text), main, special)
    }

    /** Dạng `0116192933|01` — dạng thật của vietlott.vn. */
    private fun parsePipeForm(text: String, from: Int, drawId: String): Draw? {
        val window = text.substring(from, minOf(text.length, from + 300))
        val m = PIPE_FORM.find(window) ?: return null

        val digits = m.groupValues[1].filter { it.isDigit() }
        val spDigits = m.groupValues[2].filter { it.isDigit() }
        if (digits.length != 10 || spDigits.length != 2) return null

        val main = (0 until 10 step 2)
            .map { digits.substring(it, it + 2).toInt() }
            .sorted()
        if (main.size != 5 || main.distinct().size != 5) return null
        if (main.any { it < MAIN_MIN || it > MAIN_MAX }) return null

        val special = spDigits.toInt()
        if (special < SPECIAL_MIN || special > SPECIAL_MAX) return null

        return Draw(drawId, dateOf(text), main, special)
    }

    private fun dateOf(text: String): String =
        DATE.find(text)?.let { m ->
            "${m.groupValues[3]}-${m.groupValues[2]}-${m.groupValues[1]}"
        } ?: ""

    private const val MAIN_MIN = 1
    private const val MAIN_MAX = 35
    private const val SPECIAL_MIN = 1
    private const val SPECIAL_MAX = 12
}
