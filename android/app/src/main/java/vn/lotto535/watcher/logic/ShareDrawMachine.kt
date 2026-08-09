package vn.lotto535.watcher.logic

import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime

/**
 * Máy trạng thái kỳ CHIA GIẢI Độc Đắc — cổng từ `scripts/jackpot_watch.py`.
 *
 * Thể lệ Vietlott: kết thúc một kỳ quay bất kỳ, nếu Độc Đắc VƯỢT 12 tỷ mà
 * không có người trúng, thì kỳ quay CUỐI CÙNG (21:00) của NGÀY LIỀN KẾ TIẾP
 * được xác định là kỳ "Chia Giải Độc Đắc".
 *
 * Mọi mốc thời gian đều tính theo GIỜ VIỆT NAM (UTC+7), không theo giờ máy —
 * điện thoại mang đi nước ngoài vẫn phải báo đúng ngày chia giải ở VN.
 */
object ShareDrawMachine {

    const val THRESHOLD_VND = 12_000_000_000L
    const val SHARE_DRAW_TIME = "21:00"
    val VN_ZONE: ZoneId = ZoneId.of("Asia/Ho_Chi_Minh")

    fun todayVn(): LocalDate = ZonedDateTime.now(VN_ZONE).toLocalDate()

    /** Loại sự kiện — trùng tên với bản Python để đối chiếu log cho dễ. */
    enum class Kind { SCHEDULED, REMINDER, CANCELLED, COMPLETED, SCRAPE_FAIL, NEW_DRAW }

    data class Event(
        val kind: Kind,
        val title: String,
        val message: String,
        val urgent: Boolean = false,
    )

    data class State(
        var pending: Boolean = false,
        var shareDate: String? = null,
        var reminded: Boolean = false,
        var peakJackpot: Long = 0,
        var triggerDrawId: String? = null,
        var triggerDrawDate: String? = null,
        var prevJackpot: Long = 0,
        var scrapeFailAlerted: Boolean = false,
    )

    fun fmt(vnd: Long?): String {
        if (vnd == null) return "?"
        val s = String.format("%,d", vnd).replace(',', '.')
        return if (vnd >= 1_000_000_000L)
            "$s đ (~%.1f tỷ)".format(vnd / 1e9) else "$s đ"
    }

    private fun parseDate(s: String?): LocalDate? =
        try { if (s.isNullOrBlank()) null else LocalDate.parse(s) } catch (e: Exception) { null }

    private fun dm(d: LocalDate) = "%02d/%02d".format(d.dayOfMonth, d.monthValue)
    private fun dmy(d: LocalDate) = "%02d/%02d/%d".format(d.dayOfMonth, d.monthValue, d.year)

    private fun reminderEvent(shareDate: LocalDate, peak: Long) = Event(
        Kind.REMINDER,
        "🔔 TỐI NAY: kỳ CHIA GIẢI Độc Đắc Lotto 5/35!",
        "Kỳ quay $SHARE_DRAW_TIME hôm nay (${dmy(shareDate)}) là kỳ CHIA GIẢI. " +
            "Độc Đắc ~${fmt(peak)} sẽ chia cho Giải Nhất (2/6) và Nhì/Ba/Tư/Năm " +
            "(mỗi giải 1/6) nếu không ai trúng trực tiếp. Nhớ mua vé trước giờ quay!",
        urgent = true,
    )

    /**
     * Cập nhật trạng thái sau mỗi lần cào. Trả danh sách sự kiện cần thông báo.
     * `state` bị sửa TẠI CHỖ — người gọi lưu lại sau khi hàm trả về.
     */
    fun check(
        state: State,
        jackpotVnd: Long?,
        lastDrawId: String?,
        lastDrawDate: String?,
        recentJackpots: List<Long>,
    ): List<Event> {
        val events = ArrayList<Event>()
        val today = todayVn()

        // ── Cào thất bại ────────────────────────────────────────────────────
        if (jackpotVnd == null) {
            // Nhắc "tối nay chia giải" chỉ cần shareDate + peak đã lưu, KHÔNG
            // cần pot mới. Cào lỗi không được phép nuốt mất thông báo này.
            val sd = parseDate(state.shareDate)
            if (state.pending && sd != null && today == sd && !state.reminded) {
                state.reminded = true
                events.add(reminderEvent(sd, state.peakJackpot))
                return events
            }
            if (!state.scrapeFailAlerted) {
                state.scrapeFailAlerted = true
                events.add(Event(
                    Kind.SCRAPE_FAIL,
                    "⚠️ Không lấy được số Độc Đắc",
                    "Mọi nguồn tra cứu đều lỗi, kể cả trang chính thức. Tạm thời " +
                        "không tự xác định được kỳ CHIA GIẢI — kiểm tra thủ công " +
                        "trên vietlott.vn. Chỉ báo 1 lần cho tới khi tra cứu chạy lại.",
                ))
            }
            return events
        }

        state.scrapeFailAlerted = false

        // Phát hiện pot reset bằng lịch sử: pot kỳ này thấp hơn rõ so với đỉnh
        // 3 kỳ gần nhất → đã có người trúng, kể cả khi web còn hiện số cũ.
        val valid = recentJackpots.filter { it > 1_000_000_000L }
        val droppedVsLog = valid.size >= 2 &&
            jackpotVnd < (valid.takeLast(3).maxOrNull() ?: 0L) * 0.92

        if (state.pending) {
            val shareDate = parseDate(state.shareDate)
            if (shareDate == null) {
                resetTo(state, jackpotVnd)
                return events
            }
            val peak = maxOf(state.peakJackpot, 0L)
            val prev = state.prevJackpot
            val droppedVsPrev = prev > 0 && jackpotVnd < prev * 0.95
            val droppedVsPeak = jackpotVnd < peak * 0.90

            if (droppedVsPrev || droppedVsPeak || droppedVsLog) {
                if (!today.isAfter(shareDate)) {
                    events.add(Event(
                        Kind.CANCELLED,
                        "🚫 Huỷ kỳ chia giải Lotto 5/35",
                        "Đã có người trúng Độc Đắc (~${fmt(peak)}) trước kỳ chia giải " +
                            "${dm(shareDate)}. Pot quay về ~6 tỷ.",
                    ))
                } else {
                    events.add(Event(
                        Kind.COMPLETED,
                        "✅ Kỳ chia giải Lotto 5/35 đã diễn ra",
                        "Kỳ chia giải ngày ${dmy(shareDate)} đã xong (pot trước chia " +
                            "~${fmt(peak)}). Pot hiện tại: ${fmt(jackpotVnd)}.",
                    ))
                }
                resetTo(state, jackpotVnd)
            } else {
                state.peakJackpot = maxOf(peak, jackpotVnd)
                if (today == shareDate && !state.reminded) {
                    events.add(reminderEvent(shareDate, state.peakJackpot))
                    state.reminded = true
                } else if (today.toEpochDay() - shareDate.toEpochDay() > 2) {
                    resetTo(state, jackpotVnd)   // dữ liệu trễ bất thường
                }
            }
        } else {
            if (droppedVsLog) {
                state.peakJackpot = jackpotVnd      // chu kỳ mới, không cộng dồn
            } else {
                state.peakJackpot = maxOf(state.peakJackpot, jackpotVnd)
            }

            if (jackpotVnd > THRESHOLD_VND) {
                val trigger = parseDate(lastDrawDate) ?: today
                val shareDate = trigger.plusDays(1)
                state.pending = true
                state.shareDate = shareDate.toString()
                state.reminded = false
                state.triggerDrawId = lastDrawId
                state.triggerDrawDate = trigger.toString()
                events.add(Event(
                    Kind.SCHEDULED,
                    "📅 Đã xác định kỳ CHIA GIẢI Lotto 5/35",
                    "Độc Đắc ${fmt(jackpotVnd)} đã vượt 12 tỷ sau kỳ " +
                        "#${lastDrawId ?: "?"}. Kỳ quay $SHARE_DRAW_TIME ngày " +
                        "${dmy(shareDate)} là kỳ CHIA GIẢI.",
                    urgent = true,
                ))
            }
        }

        state.prevJackpot = jackpotVnd
        return events
    }

    private fun resetTo(state: State, jackpot: Long) {
        state.pending = false
        state.shareDate = null
        state.reminded = false
        state.peakJackpot = jackpot
        state.triggerDrawId = null
        state.triggerDrawDate = null
        state.prevJackpot = jackpot
        state.scrapeFailAlerted = false
    }
}
