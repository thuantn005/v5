package vn.lotto535.watcher.data

import org.json.JSONObject

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
 * LƯU Ý TRUNG THỰC: bộ nhận dạng dưới đây là "tốt nhất có thể" chứ chưa được
 * đối chiếu với HTML thật của vietlott.vn — môi trường build trả 403 với trang
 * đó nên không kiểm chứng được tại chỗ. Vì vậy khi bóc số thất bại, app KHÔNG
 * đoán bừa mà rơi xuống `data.json` trên GitHub Pages (đã qua kiểm định chéo
 * của pipeline). Parser Độc Đắc thì khác — nó là bản cổng nguyên văn từ Python
 * đã chạy thật, nên đáng tin hơn hẳn.
 */
object DrawParser {

    private val KY = Regex("""#\s*(\d{3,6})""")
    private val DATE = Regex("""(\d{2})[/-](\d{2})[/-](\d{4})""")
    // 5 số 2 chữ số cách nhau bởi thẻ/khoảng trắng, rồi tới số đặc biệt.
    private val BALLS = Regex("""\b(0[1-9]|[12]\d|3[0-5])\b""")

    /** Cắt bỏ thẻ HTML, giữ lại text để dò số cho đỡ nhiễu. */
    private fun stripTags(html: String): String =
        html.replace(Regex("""<script[\s\S]*?</script>""", RegexOption.IGNORE_CASE), " ")
            .replace(Regex("""<style[\s\S]*?</style>""", RegexOption.IGNORE_CASE), " ")
            .replace(Regex("""<[^>]+>"""), " ")
            .replace(Regex("""\s+"""), " ")

    /**
     * Thử bóc kỳ MỚI NHẤT. Trả null nếu không chắc chắn — thà không có còn hơn
     * báo sai số cho người dùng.
     */
    fun parseLatest(html: String): Draw? {
        val text = stripTags(html)
        val ky = KY.find(text) ?: return null
        val drawId = ky.groupValues[1].padStart(5, '0')

        // Chỉ soi trong ~400 ký tự ngay sau mã kỳ: đó là khối kết quả của kỳ đó.
        val from = ky.range.last + 1
        val window = text.substring(from, minOf(text.length, from + 400))

        val hits = BALLS.findAll(window).take(5).toList()
        if (hits.size < 5) return null
        val main = hits.map { it.value.toInt() }.sorted()
        if (main.distinct().size != 5) return null

        // Số đặc biệt 1..12 là số hai chữ số đầu tiên NGAY SAU 5 số chính.
        val afterMain = window.substring(minOf(hits[4].range.last + 1, window.length))
        val special = Regex("""\b(0[1-9]|1[0-2])\b""").find(afterMain)
            ?.value?.toIntOrNull()?.takeIf { it in 1..12 }

        val date = DATE.find(text)?.let { m ->
            "${m.groupValues[3]}-${m.groupValues[2]}-${m.groupValues[1]}"
        } ?: ""

        return Draw(drawId, date, main, special)
    }

    /** Đọc kỳ mới nhất từ data.json mà pipeline công bố lên GitHub Pages. */
    fun parsePagesJson(body: String): Draw? = try {
        val root = JSONObject(body)
        val hist = root.getJSONArray("draw_history")
        var best: Draw? = null
        for (i in 0 until hist.length()) {
            val o = hist.getJSONObject(i)
            val id = o.optString("target_draw_id")
            if (id.isEmpty()) continue
            val arr = o.optJSONArray("actual_main") ?: continue
            val nums = (0 until arr.length()).map { arr.getInt(it) }
            if (nums.size != 5) continue
            val d = Draw(
                drawId = id,
                drawDate = o.optString("draw_date"),
                numbers = nums.sorted(),
                special = o.optInt("actual_special", -1).takeIf { it in 1..12 },
            )
            if (best == null || d.drawId > best!!.drawId) best = d
        }
        best
    } catch (e: Exception) {
        null
    }
}
