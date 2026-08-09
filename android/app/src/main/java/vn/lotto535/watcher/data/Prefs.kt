package vn.lotto535.watcher.data

import android.content.Context
import org.json.JSONArray
import vn.lotto535.watcher.logic.ShareDrawMachine.Kind
import vn.lotto535.watcher.logic.ShareDrawMachine.State

/** Lưu trạng thái máy chia giải + tuỳ chọn thông báo. */
class Prefs(context: Context) {

    private val sp = context.getSharedPreferences("lotto535", Context.MODE_PRIVATE)

    fun loadState(): State = State(
        pending = sp.getBoolean("pending", false),
        shareDate = sp.getString("shareDate", null),
        reminded = sp.getBoolean("reminded", false),
        peakJackpot = sp.getLong("peakJackpot", 0L),
        triggerDrawId = sp.getString("triggerDrawId", null),
        triggerDrawDate = sp.getString("triggerDrawDate", null),
        prevJackpot = sp.getLong("prevJackpot", 0L),
        scrapeFailAlerted = sp.getBoolean("scrapeFailAlerted", false),
    )

    fun saveState(s: State) = sp.edit()
        .putBoolean("pending", s.pending)
        .putString("shareDate", s.shareDate)
        .putBoolean("reminded", s.reminded)
        .putLong("peakJackpot", s.peakJackpot)
        .putString("triggerDrawId", s.triggerDrawId)
        .putString("triggerDrawDate", s.triggerDrawDate)
        .putLong("prevJackpot", s.prevJackpot)
        .putBoolean("scrapeFailAlerted", s.scrapeFailAlerted)
        .apply()

    /** Vài giá trị pot gần nhất — dùng để phát hiện pot reset. */
    fun jackpotHistory(): List<Long> = try {
        val arr = JSONArray(sp.getString("jackpotHistory", "[]"))
        (0 until arr.length()).map { arr.getLong(it) }
    } catch (e: Exception) { emptyList() }

    fun pushJackpot(v: Long) {
        val list = (jackpotHistory() + v).takeLast(6)
        sp.edit().putString("jackpotHistory", JSONArray(list).toString()).apply()
    }

    var lastDrawId: String?
        get() = sp.getString("lastDrawId", null)
        set(v) = sp.edit().putString("lastDrawId", v).apply()

    var lastJackpot: Long
        get() = sp.getLong("lastJackpot", 0L)
        set(v) = sp.edit().putLong("lastJackpot", v).apply()

    var lastCheckEpoch: Long
        get() = sp.getLong("lastCheckEpoch", 0L)
        set(v) = sp.edit().putLong("lastCheckEpoch", v).apply()

    var lastStatus: String
        get() = sp.getString("lastStatus", "Chưa kiểm tra lần nào") ?: ""
        set(v) = sp.edit().putString("lastStatus", v).apply()

    var lastDrawText: String
        get() = sp.getString("lastDrawText", "—") ?: "—"
        set(v) = sp.edit().putString("lastDrawText", v).apply()

    var lastSource: String
        get() = sp.getString("lastSource", "—") ?: "—"
        set(v) = sp.edit().putString("lastSource", v).apply()

    /** Mốc thời gian lần cào THÀNH CÔNG gần nhất — lưới an toàn dựa vào đây
     *  để biết chuỗi hẹn giờ còn sống hay đã đứt. */
    var lastSuccessEpoch: Long
        get() = sp.getLong("lastSuccessEpoch", 0L)
        set(v) = sp.edit().putLong("lastSuccessEpoch", v).apply()

    /** Đã thử lại mấy lần cho kỳ quay đang chờ. */
    var retryCount: Int
        get() = sp.getInt("retryCount", 0)
        set(v) = sp.edit().putInt("retryCount", v).apply()

    // ── Bật/tắt từng loại thông báo ─────────────────────────────────────────
    // Mặc định BẬT hai loại xoay quanh kỳ chia giải (đúng thứ bạn cần biết),
    // TẮT các loại phụ để không bị làm phiền.
    private fun defaultFor(k: Kind) = when (k) {
        Kind.SCHEDULED, Kind.REMINDER -> true
        else -> false
    }

    fun isEnabled(k: Kind): Boolean = sp.getBoolean("notify_${k.name}", defaultFor(k))

    fun setEnabled(k: Kind, on: Boolean) =
        sp.edit().putBoolean("notify_${k.name}", on).apply()
}
