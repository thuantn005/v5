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

    /** Chi tiết 1 vé trong 1 kỳ. */
    data class TicketResult(
        val index: Int,
        val windowLabel: String,
        val numbers: List<Int>,
        val special: Int,
        val mainHits: Int,        // số chính khớp
        val hitNumbers: List<Int>,// những số khớp cụ thể
        val specialHit: Boolean,
        val jackpot2: Boolean,
        val jackpot1: Boolean,
    ) {
        fun pretty(): String {
            val nums = numbers.joinToString(" ") { String.format("%02d", it) }
            val sp = String.format("%02d", special)
            val spMark = if (specialHit) " ✅ĐB" else ""
            return "[$windowLabel] $nums +$sp → $mainHits/5$spMark"
        }
    }

    data class Row(
        val drawId: String,
        val drawDate: String,
        val actualNumbers: List<Int>,
        val actualSpecial: Int,
        val tickets: List<TicketResult>,
        val bestMainHits: Int,
        val specialHit: Boolean,
        val jackpot2: Boolean,
        val jackpot1: Boolean,
    ) {
        fun prettyActual(): String {
            val nums = actualNumbers.joinToString(" ") { String.format("%02d", it) }
            return "#$drawId $drawDate  $nums +${String.format("%02d", actualSpecial)}"
        }
    }

    data class Summary(
        val rows: List<Row>,
        val evaluated: Int,
        val avgBestMainHits: Double,
        val avgBestMainRandom: Double,
        val specialHitRate: Double,
        val jackpot2: Int,
        val jackpot1: Int,
    )

    private const val MIN_HISTORY = 30
    private const val TICKETS = 5

    fun audit(history: List<Draw>, window: Int = 200): Summary {
        val sorted = history
            .filter { it.numbers.size == 5 && it.special != null }
            .sortedBy { it.drawId }
        val rows = ArrayList<Row>()

        var randomBest = 0
        val startIdx = maxOf(MIN_HISTORY, sorted.size - window)
        for (i in startIdx until sorted.size) {
            val target = sorted[i]
            val prior = sorted.subList(0, i)
            if (prior.size < MIN_HISTORY) continue

            val tickets = Predictor.predict(prior, target.drawId, TICKETS)
            if (tickets.isEmpty()) continue

            val actualMain = target.numbers.toSet()
            val ticketResults = tickets.map { t ->
                val hits = t.numbers.filter { it in actualMain }
                val spHit = t.special == target.special
                TicketResult(
                    index       = t.index,
                    windowLabel = t.windowLabel,
                    numbers     = t.numbers,
                    special     = t.special,
                    mainHits    = hits.size,
                    hitNumbers  = hits.sorted(),
                    specialHit  = spHit,
                    jackpot2    = hits.size == 5,
                    jackpot1    = hits.size == 5 && spHit,
                )
            }

            val best = ticketResults.maxOf { it.mainHits }
            rows.add(Row(
                drawId        = target.drawId,
                drawDate      = target.drawDate ?: "",
                actualNumbers = target.numbers.sorted(),
                actualSpecial = target.special ?: 0,
                tickets       = ticketResults,
                bestMainHits  = best,
                specialHit    = ticketResults.any { it.specialHit },
                jackpot2      = ticketResults.any { it.jackpot2 },
                jackpot1      = ticketResults.any { it.jackpot1 },
            ))

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
