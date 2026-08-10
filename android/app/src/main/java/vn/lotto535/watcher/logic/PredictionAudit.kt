package vn.lotto535.watcher.logic

import vn.lotto535.watcher.data.Draw

/**
 * "Bảng vàng" TRÊN MÁY: dựng lại vé đã dự đoán cho mỗi kỳ QUÁ KHỨ rồi đối
 * chiếu với kết quả thật.
 *
 * Làm được vì Predictor gieo số bằng seed cố định từ mã kỳ — vé dự đoán cho
 * kỳ #N luôn tái lập y hệt. Để TRUNG THỰC (không nhìn tương lai), khi chấm kỳ
 * #N chỉ dùng lịch sử các kỳ TRƯỚC nó; đúng cách backtest tiến.
 *
 * NÓI THẲNG: bảng này để bạn tự thấy công thức KHÔNG có lợi thế, chứ không
 * phải để khoe nó có. Mốc so sánh là ngẫu nhiên thuần: trúng trung bình
 * 5·5/35 = 0,7143 số chính/kỳ, trúng ĐB 1/12 = 8,33%.
 */
object PredictionAudit {

    data class Row(
        val drawId: String,
        val bestMainHits: Int,      // số chính trúng nhiều nhất trong 5 vé
        val specialHit: Boolean,    // có vé nào trúng cả ĐB không
        val jackpot2: Boolean,      // vé nào trúng đủ 5 số chính
        val jackpot1: Boolean,      // 5 chính + ĐB
    )

    data class Summary(
        val rows: List<Row>,
        val evaluated: Int,
        val avgBestMainHits: Double,
        /** Mốc CÔNG BẰNG: best-của-5-vé NGẪU NHIÊN trên đúng các kỳ ấy. So
         *  best-của-5 với 0,7143 (mốc 1 vé) là gian lận — đây mới đúng. */
        val avgBestMainRandom: Double,
        val specialHitRate: Double,
        val jackpot2: Int,
        val jackpot1: Int,
    )

    private const val MIN_HISTORY = 30      // cần đủ lịch sử trước khi chấm
    private const val TICKETS = 5

    /**
     * Chấm các kỳ gần nhất (tối đa `window`). Với mỗi kỳ, dựng lại vé dự đoán
     * TỪ lịch sử trước đó rồi so với kết quả thật.
     *
     * Mặc định 200 kỳ, KHÔNG phải 40: đo trên 40 kỳ, công thức trông hơn ngẫu
     * nhiên (+0,1) nhưng đó là nhiễu — thêm kỳ vào thì chênh lệch co về ~0
     * (600 kỳ: +0,01). Cửa sổ nhỏ dễ tạo ảo giác có lợi thế.
     */
    fun audit(history: List<Draw>, window: Int = 200): Summary {
        val sorted = history
            .filter { it.numbers.size == 5 && it.special != null }
            .sortedBy { it.drawId }
        val rows = ArrayList<Row>()

        var randomBest = 0
        val startIdx = maxOf(MIN_HISTORY, sorted.size - window)
        for (i in startIdx until sorted.size) {
            val target = sorted[i]
            val prior = sorted.subList(0, i)          // CHỈ quá khứ — không rò tương lai
            if (prior.size < MIN_HISTORY) continue

            val tickets = Predictor.predict(prior, target.drawId, TICKETS)
            if (tickets.isEmpty()) continue

            val actualMain = target.numbers.toSet()
            var bestMain = 0
            var special = false
            var jp2 = false
            var jp1 = false
            for (t in tickets) {
                val hits = t.numbers.count { it in actualMain }
                if (hits > bestMain) bestMain = hits
                val sp = (t.special == target.special)
                if (sp) special = true
                if (hits == 5) { jp2 = true; if (sp) jp1 = true }
            }
            rows.add(Row(target.drawId, bestMain, special, jp2, jp1))

            // Mốc công bằng: 5 vé NGẪU NHIÊN cho đúng kỳ này, lấy best.
            val rng = java.util.Random(target.drawId.hashCode().toLong() * 31 + 7)
            var rb = 0
            repeat(TICKETS) {
                val pick = HashSet<Int>()
                while (pick.size < 5) pick.add(1 + rng.nextInt(35))
                val h = pick.count { it in actualMain }
                if (h > rb) rb = h
            }
            randomBest += rb
        }

        val n = rows.size
        return Summary(
            rows = rows.sortedByDescending { it.drawId },
            evaluated = n,
            avgBestMainHits = if (n > 0) rows.sumOf { it.bestMainHits }.toDouble() / n else 0.0,
            avgBestMainRandom = if (n > 0) randomBest.toDouble() / n else 0.0,
            specialHitRate = if (n > 0) rows.count { it.specialHit }.toDouble() / n else 0.0,
            jackpot2 = rows.count { it.jackpot2 },
            jackpot1 = rows.count { it.jackpot1 },
        )
    }
}
