package vn.lotto535.watcher.logic

import kotlin.math.absoluteValue
import vn.lotto535.watcher.data.Draw

/**
 * Sinh vé dự đoán cho kỳ tới, tính NGAY TRÊN MÁY từ lịch sử đã lưu.
 *
 * Công thức là bản rút gọn của nhóm "kết hợp 3 dấu hiệu" trên dashboard:
 * tần suất gần đây + tần suất toàn lịch sử + số kỳ vắng mặt, rồi BỐC NGẪU
 * NHIÊN theo trọng số đó (không lấy tất định 5 số điểm cao nhất, vì làm vậy
 * thì 30 số còn lại không bao giờ có cửa).
 *
 * PHẢI NÓI RÕ: backtest trên 600 kỳ với 19 model cho thấy KHÔNG công thức nào
 * vượt được ngẫu nhiên thuần — vé ngẫu nhiên còn về nhì. Mọi vé đều đúng
 * 1/324.632 (J2) và 1/3.895.584 (J1). Phần này để chọn số cho vui và tái lập
 * được, không phải để tăng cơ hội trúng. Nếu nó tăng được thì bài toán xổ số
 * đã không còn là xổ số.
 */
object Predictor {

    private const val MAIN_MIN = 1
    private const val MAIN_MAX = 35
    private const val SPECIAL_MIN = 1
    private const val SPECIAL_MAX = 12
    private const val RECENT_WINDOW = 200

    data class Ticket(val index: Int, val numbers: List<Int>, val special: Int) {
        fun pretty(): String {
            val m = numbers.joinToString(" ") { String.format("%02d", it) }
            return "$m + ĐB ${String.format("%02d", special)}"
        }
    }

    /** Seed tái lập từ chuỗi — cùng kỳ, cùng số thứ tự thì luôn ra cùng vé. */
    private fun seedOf(trace: String): Long {
        var h = 1125899906842597L                    // FNV-ish, đủ dùng
        for (c in trace) h = 31 * h + c.code
        return h.absoluteValue
    }

    private fun norm(v: DoubleArray): DoubleArray {
        val mx = v.maxOrNull() ?: 0.0
        if (mx <= 0.0) return DoubleArray(v.size) { 0.0 }
        return DoubleArray(v.size) { v[it] / mx }
    }

    /**
     * @param history toàn bộ kỳ đã lưu (thứ tự nào cũng được)
     * @param nextDrawId mã kỳ sắp quay, dùng làm seed
     * @param count số vé muốn sinh
     */
    fun predict(history: List<Draw>, nextDrawId: String, count: Int = 5): List<Ticket> {
        if (history.isEmpty()) return emptyList()
        val sorted = history.sortedBy { it.drawId }

        val size = MAIN_MAX - MAIN_MIN + 1
        val all = DoubleArray(size)
        val recent = DoubleArray(size)
        val lastSeen = IntArray(size) { -1 }
        val spFreq = DoubleArray(SPECIAL_MAX - SPECIAL_MIN + 1)

        val recentFrom = maxOf(0, sorted.size - RECENT_WINDOW)
        for ((i, d) in sorted.withIndex()) {
            for (n in d.numbers) {
                if (n !in MAIN_MIN..MAIN_MAX) continue
                val j = n - MAIN_MIN
                all[j] += 1.0
                if (i >= recentFrom) recent[j] += 1.0
                lastSeen[j] = i
            }
            d.special?.let { if (it in SPECIAL_MIN..SPECIAL_MAX) spFreq[it - SPECIAL_MIN] += 1.0 }
        }

        // Số kỳ vắng mặt, chuẩn hoá theo kỳ gần nhất.
        val last = sorted.size - 1
        val overdue = DoubleArray(size) { j ->
            if (lastSeen[j] < 0) sorted.size.toDouble() else (last - lastSeen[j]).toDouble()
        }

        val na = norm(all); val nr = norm(recent); val no = norm(overdue)
        val w = DoubleArray(size) { 0.1 + nr[it] + na[it] + no[it] }
        val sw = DoubleArray(spFreq.size) { 0.1 + spFreq[it] }

        return (1..count).map { idx ->
            val rng = java.util.Random(seedOf("L535-$nextDrawId-P$idx"))
            Ticket(
                index = idx,
                numbers = sampleWithoutReplacement(w, 5, MAIN_MIN, rng).sorted(),
                special = sampleWithoutReplacement(sw, 1, SPECIAL_MIN, rng).first(),
            )
        }
    }

    /** Bốc k phần tử không hoàn lại, xác suất tỉ lệ với trọng số. */
    private fun sampleWithoutReplacement(
        weights: DoubleArray, k: Int, offset: Int, rng: java.util.Random,
    ): List<Int> {
        val w = weights.copyOf()
        val out = ArrayList<Int>(k)
        repeat(minOf(k, w.size)) {
            val total = w.sum()
            if (total <= 0.0) {
                val free = w.indices.filter { i -> w[i] > 0.0 }
                out.add(offset + (free.randomOrNull(rng) ?: 0))
                return@repeat
            }
            var r = rng.nextDouble() * total
            for (i in w.indices) {
                r -= w[i]
                if (r <= 0.0) {
                    out.add(offset + i)
                    w[i] = 0.0
                    return@repeat
                }
            }
            val i = w.indices.last { w[it] > 0.0 }
            out.add(offset + i)
            w[i] = 0.0
        }
        return out
    }

    private fun List<Int>.randomOrNull(rng: java.util.Random): Int? =
        if (isEmpty()) null else this[rng.nextInt(size)]
}
