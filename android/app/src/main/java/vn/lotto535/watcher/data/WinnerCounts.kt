package vn.lotto535.watcher.data

import kotlin.math.abs
import kotlin.math.sqrt

/**
 * Số người trúng mỗi bậc giải một kỳ — dữ liệu ĐO thiên lệch chọn số đám đông.
 *
 * Cổng nguyên văn từ scripts/fetch_winner_counts.py. Nguồn: minhchinh.com
 * (bên thứ ba, KHÔNG sau WAF của vietlott, nên điện thoại lẫn CI đều đọc được;
 * đã dò xác nhận vietlott.vn / vietlott-sms.vn trả 403 với IP máy chủ).
 */
data class WinnerCounts(
    val drawId: String,
    val jackpot: Int = -1,
    val first: Int = -1,
    val second: Int = -1,
    val third: Int = -1,
    val fourth: Int = -1,      // 3 số chính + ĐB
    val fifth: Int = -1,       // 3 số chính, KHÔNG ĐB
    val kk: Int = -1,
) {
    fun hasCore() = fourth >= 0 && fifth >= 0
}

object WinnerCountsParser {

    private val KY = Regex("""#\s*(\d{3,6})""")
    private val TAGS = Regex("""<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>""",
        RegexOption.IGNORE_CASE)

    // (khoá, tên bậc trong bảng). Tiền tố "giải" là TUỲ CHỌN — hàng Độc Đắc
    // ghi "Độc đắc" (sau "Giá trị"), không có chữ "giải".
    private val TIERS = listOf(
        "jackpot" to "độc đắc", "first" to "nhất", "second" to "nhì",
        "third" to "ba", "fourth" to "tư", "fifth" to "năm", "kk" to "kk",
    )

    private fun clean(html: String): String =
        TAGS.replace(html, " ").replace(Regex("""\s+"""), " ")

    /** Bóc bảng số người trúng của kỳ mới nhất, hoặc null nếu không có bảng. */
    fun parse(html: String): WinnerCounts? {
        val t = clean(html)
        val ky = KY.find(t) ?: return null
        val drawId = ky.groupValues[1].padStart(5, '0')
        val low = t.lowercase()

        val vals = HashMap<String, Int>()
        for ((key, name) in TIERS) {
            // "giải <tên> <số người> <giá trị có phân cách>"
            val re = Regex("""(?:gi[ải]+\s+)?""" + Regex.escape(name) +
                """\b[^\d]{0,20}([\d.,]+)\s+([\d.,]{4,})""")
            val m = re.find(low) ?: continue
            val n = m.groupValues[1].filter { it.isDigit() }.toIntOrNull() ?: continue
            vals[key] = n
        }
        if (vals.isEmpty()) return null
        return WinnerCounts(
            drawId = drawId,
            jackpot = vals["jackpot"] ?: -1,
            first = vals["first"] ?: -1,
            second = vals["second"] ?: -1,
            third = vals["third"] ?: -1,
            fourth = vals["fourth"] ?: -1,
            fifth = vals["fifth"] ?: -1,
            kk = vals["kk"] ?: -1,
        )
    }
}

/**
 * Đo thiên lệch chọn SỐ ĐẶC BIỆT từ nhiều kỳ đã gom.
 *
 * Giải Tư (3 chính + ĐB) và Giải Năm (3 chính, không ĐB) đòi hỏi y hệt nhau về
 * số chính. Gộp mọi kỳ: tổng Tư / (tổng Tư + tổng Năm) = tỉ lệ người chơi chọn
 * ĐÚNG số ĐB của kỳ. So với 1/12 = 8,33%.
 */
object CrowdBias {

    data class Result(
        val draws: Int,
        val fourthTotal: Int,
        val fifthTotal: Int,
        val pickedFraction: Double,     // tỉ lệ chọn trúng ĐB
        val z: Double,
        val pValue: Double,
        val significant: Boolean,
    )

    private const val UNIFORM = 1.0 / 12.0

    fun analyze(rows: List<WinnerCounts>): Result? {
        val usable = rows.filter { it.hasCore() }
        val a = usable.sumOf { it.fourth }
        val b = usable.sumOf { it.fifth }
        if (a + b == 0) return null
        val frac = a.toDouble() / (a + b)
        val se = sqrt(frac * (1 - frac) / (a + b))
        val z = if (se > 0) (frac - UNIFORM) / se else 0.0
        val p = erfc(abs(z) / sqrt(2.0))
        return Result(usable.size, a, b, frac, z, p, p < 0.05)
    }

    /** erfc xấp xỉ (Abramowitz–Stegun 7.1.26) — không có java.lang.Math.erfc. */
    private fun erfc(x: Double): Double {
        val z = abs(x)
        val t = 1.0 / (1.0 + 0.5 * z)
        val ans = t * kotlin.math.exp(-z * z - 1.26551223 + t * (1.00002368 +
            t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 +
            t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 +
            t * 0.17087277)))))))))
        return if (x >= 0) ans else 2.0 - ans
    }
}
