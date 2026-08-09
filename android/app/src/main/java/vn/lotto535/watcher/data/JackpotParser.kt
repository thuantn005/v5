package vn.lotto535.watcher.data

/**
 * Bóc giá trị Độc Đắc ra khỏi HTML.
 *
 * Cổng nguyên văn từ `scripts/jackpot_check.py::_extract_jackpot` — cùng bộ
 * nhãn, cùng danh sách decoy, cùng cửa sổ 200 ký tự, cùng cách gắn mã kỳ. Giữ
 * giống hệt là có chủ đích: parser bên Python đã chạy thật nhiều tháng trên
 * xosominhngoc và minhchinh, nên mọi khác biệt ở đây đều là rủi ro thuần tuý.
 */
object JackpotParser {

    private const val MIN_VND = 1_000_000_000L
    private const val MAX_VND = 500_000_000_000L
    private const val LABEL_WINDOW = 200

    private val LABELS = listOf("độc đắc", "doc dac", "jackpot")

    /** Cụm báo hiệu con số KHÔNG phải pot hiện tại (ước tính, doanh thu…). */
    private val DECOYS = listOf(
        "ước tính", "uoc tinh", "kỳ tới", "ky toi", "dự kiến", "du kien",
        "doanh thu", "doanh số", "doanh so", "tổng giá trị", "luỹ kế", "lũy kế",
    )

    private val MONEY = Regex("""([\d][\d.,]{8,})(?:\s*(?:đồng|dong|vnd))?""",
        RegexOption.IGNORE_CASE)
    private val KY = Regex("""#\s*(\d{3,6})""")

    data class Result(val amountVnd: Long?, val drawId: String?)

    private fun labelPositions(low: String): List<Int> {
        val out = ArrayList<Int>()
        for (label in LABELS) {
            var i = low.indexOf(label)
            while (i >= 0) {
                out.add(i)
                i = low.indexOf(label, i + 1)
            }
        }
        out.sort()
        return out
    }

    /** Mã kỳ '#NNNNN' gần nhất đứng TRƯỚC vị trí pos. */
    private fun drawIdBefore(html: String, pos: Int): String? {
        var best: String? = null
        for (m in KY.findAll(html)) {
            if (m.range.first < pos) best = m.groupValues[1] else break
        }
        return best
    }

    fun extract(html: String, expectedDrawId: String? = null): Result {
        val low = html.lowercase()
        val labels = labelPositions(low)

        // (giá trị, khoảng cách tới nhãn, kỳ)
        val candidates = ArrayList<Triple<Long, Int, String?>>()

        for (m in MONEY.findAll(html)) {
            val raw = m.groupValues[1]
            // Bắt buộc có dấu phân cách nghìn — loại các chuỗi số dính liền
            // kiểu "1419252830" vốn là mã, không phải tiền.
            if (!raw.contains('.') && !raw.contains(',')) continue
            val digits = raw.filter { it.isDigit() }
            if (digits.isEmpty()) continue
            val v = digits.toLongOrNull() ?: continue
            if (v < MIN_VND || v > MAX_VND) continue

            val pos = m.range.first
            val hasUnit = m.value.lowercase().trimEnd().let {
                it.endsWith("đồng") || it.endsWith("dong") || it.endsWith("vnd")
            }

            if (labels.isEmpty()) {
                if (hasUnit) candidates.add(Triple(v, Int.MAX_VALUE, drawIdBefore(html, pos)))
                continue
            }

            val preceding = labels.filter { pos - it in 0..LABEL_WINDOW }
            if (preceding.isEmpty()) continue
            val nearest = preceding.max()
            val between = low.substring(nearest, pos)
            if (DECOYS.any { between.contains(it) }) continue
            candidates.add(Triple(v, pos - nearest, drawIdBefore(html, pos)))
        }

        if (candidates.isEmpty()) return Result(null, null)

        // KIỂM ĐỊNH THEO KỲ. Trang chưa cập nhật vẫn hiển thị pot của kỳ TRƯỚC;
        // nuốt con số đó vào sẽ làm máy trạng thái tưởng pot vừa tụt và huỷ oan
        // kỳ chia giải. Nên: loại mọi ứng viên có kỳ CŨ hơn kỳ đã biết, ưu tiên
        // ứng viên khớp đúng kỳ, và nếu không còn ứng viên hợp lệ nào thì trả
        // về rỗng — thà không có số còn hơn hành động trên số cũ.
        val exp = expectedDrawId?.toIntOrNull()
        val pool: List<Triple<Long, Int, String?>>
        if (exp == null) {
            pool = candidates
        } else {
            val valid = candidates.filter {
                val ky = it.third?.toIntOrNull()
                ky == null || ky >= exp
            }
            val exact = valid.filter { it.third?.toIntOrNull() == exp }
            pool = if (exact.isNotEmpty()) exact else valid
            if (pool.isEmpty()) return Result(null, null)
        }

        // Nhãn gần nhất thắng; hoà khoảng cách thì lấy giá trị lớn hơn.
        val best = pool.sortedWith(
            compareBy<Triple<Long, Int, String?>> { it.second }.thenByDescending { it.first }
        ).first()
        return Result(best.first, best.third)
    }
}
