package vn.lotto535.watcher.logic

import java.security.MessageDigest
import java.util.Random
import vn.lotto535.watcher.data.CrowdBias
import vn.lotto535.watcher.data.WinnerCounts

/**
 * Chọn số NGƯỢC ĐÁM ĐÔNG — cổng từ scripts/anti_crowd.py.
 *
 * KHÔNG làm dễ trúng hơn (đã đo: 19 model, 684k vé-kỳ, khớp may rủi). Chỉ tăng
 * SỐ TIỀN NHẬN KHI TRÚNG, bằng cách né tổ hợp đông người chọn — biến số duy
 * nhất người chơi điều khiển được.
 *
 * Số ĐB dùng bản đồ ĐO THẬT nếu app đã gom đủ bảng số người trúng; chưa đủ thì
 * lùi về điểm đo duy nhất hiện có (ĐB 01 bị né 27%, p=5,5e-06 kỳ #00814).
 */
object AntiCrowd {

    private const val MAIN_MIN = 1
    private const val MAIN_MAX = 35
    private const val SPECIAL_MIN = 1
    private const val SPECIAL_MAX = 12

    data class Ticket(val index: Int, val numbers: List<Int>, val special: Int) {
        fun pretty(): String {
            val m = numbers.joinToString(" ") { "%02d".format(it) }
            return "$m + ĐB %02d".format(special)
        }
    }

    /** Lý do tổ hợp này ĐÔNG người chọn; rỗng = vắng vẻ. */
    fun reasonsCrowded(nums: List<Int>): List<String> {
        val s = nums.sorted()
        val bad = ArrayList<String>()
        if (s.all { it <= 31 }) bad.add("cả 5 số ≤31 (vùng ngày sinh)")
        val sum = s.sum()
        if (sum < 70) bad.add("tổng $sum quá thấp")
        if (sum > 110) bad.add("tổng $sum quá cao")
        var run = 1
        for (i in 1..4) {
            run = if (s[i] == s[i - 1] + 1) run + 1 else 1
            if (run >= 3) { bad.add("có 3 số liên tiếp"); break }
        }
        val d = s[1] - s[0]
        if (d > 0 && (0..3).all { s[it + 1] - s[it] == d }) bad.add("cấp số cộng bước $d")
        if (s.map { (it - 1) / 10 }.toSet().size <= 2) bad.add("dồn trong ≤2 chục")
        if (s.map { it % 10 }.toSet().size <= 2) bad.add("≤2 chữ số cuối khác nhau")
        val odd = s.count { it % 2 == 1 }
        if (odd == 0 || odd == 5) bad.add("toàn chẵn hoặc toàn lẻ")
        return bad
    }

    private fun mainWeights(): DoubleArray = DoubleArray(35) { i ->
        val n = i + 1
        when {
            n >= 32 -> 3.0        // ngoài vùng ngày — vắng nhất
            n > 12 -> 1.6         // ngoài vùng tháng
            else -> 1.0           // 1..12 vừa ngày vừa tháng — đông nhất
        }
    }

    /**
     * Trọng số số ĐB. Nếu có bản đồ đo (nhiều kỳ) thì dùng nó; chưa đủ dữ liệu
     * thì chỉ biết chắc ĐB 01 bị né, ưu tiên nhẹ 01.
     */
    private fun specialWeights(rows: List<WinnerCounts>): DoubleArray {
        val bias = CrowdBias.analyze(rows)
        val w = DoubleArray(12) { 1.0 }
        // Chỉ số ĐB 01 hiện đo được (Giải Tư/Năm gộp). Nếu có ý nghĩa thống kê,
        // đẩy trọng số 01 lên tỉ lệ nghịch với mức đám đông chọn.
        if (bias != null && bias.significant && bias.pickedFraction > 0) {
            val underpick = bias.pickedFraction / (1.0 / 12.0)   // <1 = bị né
            if (underpick < 1.0) w[0] = 1.0 / underpick
        } else {
            w[0] = 1.0 / 0.73    // điểm đo #00814: 01 chọn bằng 73% mức đều
        }
        return w
    }

    private fun seed(trace: String): Long {
        val h = MessageDigest.getInstance("SHA-256").digest(trace.toByteArray())
        var v = 0L
        for (i in 0 until 8) v = (v shl 8) or (h[i].toLong() and 0xFF)
        return v and Long.MAX_VALUE
    }

    private fun sample(weights: DoubleArray, k: Int, offset: Int, rng: Random): List<Int> {
        val w = weights.copyOf()
        val out = ArrayList<Int>(k)
        repeat(k) {
            val tot = w.sum()
            var r = rng.nextDouble() * tot
            for (i in w.indices) {
                r -= w[i]
                if (r <= 0) { out.add(offset + i); w[i] = 0.0; return@repeat }
            }
            val i = w.indices.last { w[it] > 0 }
            out.add(offset + i); w[i] = 0.0
        }
        return out
    }

    fun generate(
        drawId: String, count: Int, winnerRows: List<WinnerCounts>,
        maxTries: Int = 5000,
    ): List<Ticket> {
        val wm = mainWeights()
        val ws = specialWeights(winnerRows)
        val out = ArrayList<Ticket>(count)
        val seen = HashSet<List<Int>>()
        var idx = 0
        while (out.size < count && idx < maxTries) {
            idx++
            val rng = Random(seed("L535-anticrowd-$drawId-$idx"))
            val nums = sample(wm, 5, MAIN_MIN, rng).sorted()
            val sp = sample(ws, 1, SPECIAL_MIN, rng).first()
            val key = nums + sp
            if (key in seen || reasonsCrowded(nums).isNotEmpty()) continue
            seen.add(key)
            out.add(Ticket(out.size + 1, nums, sp))
        }
        return out
    }
}
