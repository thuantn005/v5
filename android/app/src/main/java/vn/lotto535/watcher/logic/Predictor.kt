package vn.lotto535.watcher.logic

import kotlin.math.absoluteValue
import vn.lotto535.watcher.data.Draw

/**
 * Sinh vé dự đoán cho kỳ tới, tính NGAY TRÊN MÁY từ lịch sử đã lưu.
 *
 * Mỗi vé dùng một cửa sổ lịch sử khác nhau để đa dạng góc nhìn:
 *   Vé 1 — 20 kỳ gần nhất   (ngắn hạn, bắt xu hướng nóng/lạnh ngay)
 *   Vé 2 — 50 kỳ gần nhất   (trung ngắn)
 *   Vé 3 — 100 kỳ gần nhất  (trung hạn)
 *   Vé 4 — 200 kỳ gần nhất  (trung dài)
 *   Vé 5 — toàn bộ lịch sử  (dài hạn, tần suất tổng thể)
 *
 * Mỗi vé kết hợp 3 dấu hiệu trong cửa sổ của nó:
 *   Dấu 1 — tần suất trong cửa sổ (số ra nhiều → trọng số cao)
 *   Dấu 2 — tần suất toàn lịch sử  (nền tổng thể)
 *   Dấu 3 — số kỳ vắng mặt         (cold bonus)
 * rồi BỐC NGẪU NHIÊN theo trọng số đó — không lấy tất định 5 số điểm cao
 * nhất, để 30 số còn lại vẫn có cơ hội.
 *
 * PHẢI NÓI RÕ: backtest 600 kỳ với 19 model cho thấy KHÔNG công thức nào
 * vượt được ngẫu nhiên thuần. Mọi vé đều đúng 1/324.632 (J2) và
 * 1/3.895.584 (J1). Đây là cách chọn số có thể tái lập, không phải lợi thế.
 */
object Predictor {

    private const val MAIN_MIN    = 1
    private const val MAIN_MAX    = 35
    private const val SPECIAL_MIN = 1
    private const val SPECIAL_MAX = 12

    /** Cửa sổ lịch sử cho từng vé — index 0 = vé 1. */
    private val WINDOWS = listOf(20, 50, 100, 200, Int.MAX_VALUE)
    private val WINDOW_LABELS = listOf("20 kỳ", "50 kỳ", "100 kỳ", "200 kỳ", "toàn bộ")

    data class Ticket(
        val index: Int,
        val numbers: List<Int>,
        val special: Int,
        val windowLabel: String,
    ) {
        fun pretty(): String {
            val m = numbers.joinToString(" ") { String.format("%02d", it) }
            return "$m + ĐB ${String.format("%02d", special)}"
        }
        fun label(): String = "Vé $index [cửa sổ $windowLabel]   ${pretty()}"
    }

    /** Seed tái lập từ chuỗi — cùng kỳ, cùng vé thì luôn ra cùng số. */
    private fun seedOf(trace: String): Long {
        var h = 1125899906842597L
        for (c in trace) h = 31 * h + c.code
        return h.absoluteValue
    }

    private fun norm(v: DoubleArray): DoubleArray {
        val mx = v.maxOrNull() ?: 0.0
        if (mx <= 0.0) return DoubleArray(v.size) { 0.0 }
        return DoubleArray(v.size) { v[it] / mx }
    }

    /**
     * @param history  toàn bộ kỳ đã lưu
     * @param nextDrawId  mã kỳ sắp quay, dùng làm seed
     * @param count    số vé (mặc định 5, mỗi vé 1 cửa sổ)
     */
    fun predict(history: List<Draw>, nextDrawId: String, count: Int = 5): List<Ticket> {
        if (history.isEmpty()) return emptyList()
        val sorted = history.sortedBy { it.drawId }
        val size   = MAIN_MAX - MAIN_MIN + 1
        val spSize = SPECIAL_MAX - SPECIAL_MIN + 1

        // Tần suất TOÀN lịch sử — dùng làm nền chung cho cả 5 vé
        val freqAll  = DoubleArray(size)
        val spFreqAll = DoubleArray(spSize)
        val lastSeen = IntArray(size) { -1 }
        for ((i, d) in sorted.withIndex()) {
            for (n in d.numbers) {
                if (n !in MAIN_MIN..MAIN_MAX) continue
                freqAll[n - MAIN_MIN] += 1.0
                lastSeen[n - MAIN_MIN] = i
            }
            d.special?.let {
                if (it in SPECIAL_MIN..SPECIAL_MAX) spFreqAll[it - SPECIAL_MIN] += 1.0
            }
        }

        // Số kỳ vắng mặt (dùng toàn lịch sử)
        val last = sorted.size - 1
        val overdue = DoubleArray(size) { j ->
            if (lastSeen[j] < 0) sorted.size.toDouble()
            else (last - lastSeen[j]).toDouble()
        }
        val na = norm(freqAll)
        val no = norm(overdue)

        return (1..count).map { idx ->
            val window = WINDOWS.getOrElse(idx - 1) { Int.MAX_VALUE }
            val label  = WINDOW_LABELS.getOrElse(idx - 1) { "toàn bộ" }

            // Tần suất trong cửa sổ riêng của vé này
            val recentFrom = maxOf(0, sorted.size - window)
            val freqWin   = DoubleArray(size)
            val spFreqWin = DoubleArray(spSize)
            for (i in recentFrom until sorted.size) {
                val d = sorted[i]
                for (n in d.numbers) {
                    if (n !in MAIN_MIN..MAIN_MAX) continue
                    freqWin[n - MAIN_MIN] += 1.0
                }
                d.special?.let {
                    if (it in SPECIAL_MIN..SPECIAL_MAX) spFreqWin[it - SPECIAL_MIN] += 1.0
                }
            }
            val nr = norm(freqWin)
            val sr = norm(spFreqWin)
            val sa = norm(spFreqAll)

            // Trọng số: 40% cửa sổ + 30% toàn lịch sử + 30% cold
            val w  = DoubleArray(size)  { 0.1 + 0.4 * nr[it] + 0.3 * na[it] + 0.3 * no[it] }
            val sw = DoubleArray(spSize) { 0.1 + 0.5 * sr[it] + 0.5 * sa[it] }

            val rng = java.util.Random(seedOf("L535-$nextDrawId-W$idx"))
            Ticket(
                index       = idx,
                numbers     = sampleWithoutReplacement(w, 5, MAIN_MIN, rng).sorted(),
                special     = sampleWithoutReplacement(sw, 1, SPECIAL_MIN, rng).first(),
                windowLabel = label,
            )
        }
    }

    /** Bốc k phần tử không hoàn lại, xác suất tỉ lệ với trọng số. */
    private fun sampleWithoutReplacement(
        weights: DoubleArray, k: Int, offset: Int, rng: java.util.Random,
    ): List<Int> {
        val w   = weights.copyOf()
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
                if (r <= 0.0) { out.add(offset + i); w[i] = 0.0; return@repeat }
            }
            val i = w.indices.last { w[it] > 0.0 }
            out.add(offset + i); w[i] = 0.0
        }
        return out
    }

    private fun List<Int>.randomOrNull(rng: java.util.Random): Int? =
        if (isEmpty()) null else this[rng.nextInt(size)]
}
