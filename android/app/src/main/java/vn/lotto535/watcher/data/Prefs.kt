package vn.lotto535.watcher.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
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

    /**
     * LỊCH SỬ KỲ QUAY — tự tích luỹ.
     *
     * Trang chính thức chỉ đăng kỳ gần nhất, nên lịch sử không tải về một lần
     * được mà phải gom dần qua từng lần cào. Giữ 60 kỳ gần nhất là quá đủ để
     * dò vé và để nhìn ra chỗ thủng.
     */
    fun history(): List<Draw> = try {
        val arr = JSONArray(sp.getString("history", "[]"))
        (0 until arr.length()).map { i ->
            val o = arr.getJSONObject(i)
            val nums = o.getJSONArray("n")
            Draw(
                drawId = o.getString("id"),
                drawDate = o.optString("d"),
                numbers = (0 until nums.length()).map { nums.getInt(it) },
                special = o.optInt("s", -1).takeIf { it in 1..12 },
            )
        }
    } catch (e: Exception) { emptyList() }

    /** Gộp các kỳ mới vào lịch sử; trùng mã kỳ thì bản mới ghi đè. */
    fun addDraws(list: List<Draw>) {
        if (list.isEmpty()) return
        val byId = LinkedHashMap<String, Draw>()
        for (d in history()) byId[d.drawId] = d
        for (d in list) byId[d.drawId] = d
        val kept = byId.values.sortedByDescending { it.drawId }.take(60)
        val arr = JSONArray()
        for (d in kept) {
            arr.put(JSONObject().apply {
                put("id", d.drawId)
                put("d", d.drawDate)
                put("n", JSONArray(d.numbers))
                put("s", d.special ?: -1)
            })
        }
        sp.edit().putString("history", arr.toString()).apply()
    }

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

    /** Cho phép dùng nguồn dự phòng khi vietlott.vn không vào được.
     *  MẶC ĐỊNH TẮT — app chỉ đọc trang chính thức. */
    var useMirrors: Boolean
        get() = sp.getBoolean("useMirrors", false)
        set(v) = sp.edit().putBoolean("useMirrors", v).apply()

    /** Đã thử lại mấy lần cho kỳ quay đang chờ. */
    var retryCount: Int
        get() = sp.getInt("retryCount", 0)
        set(v) = sp.edit().putInt("retryCount", v).apply()

    // ── Bật/tắt từng loại thông báo ─────────────────────────────────────────
    // Mặc định BẬT hai loại xoay quanh kỳ chia giải (đúng thứ bạn cần biết),
    // TẮT các loại phụ để không bị làm phiền.
    private fun defaultFor(k: Kind) = when (k) {
        // MISSED là cảnh báo TOÀN VẸN DỮ LIỆU: app biết mình đã bỏ sót kỳ nào.
        // Tắt nó đi thì lỗ hổng trở lại im lặng, nên mặc định luôn bật.
        Kind.SCHEDULED, Kind.REMINDER, Kind.MISSED -> true
        else -> false
    }

    fun isEnabled(k: Kind): Boolean = sp.getBoolean("notify_${k.name}", defaultFor(k))

    fun setEnabled(k: Kind, on: Boolean) =
        sp.edit().putBoolean("notify_${k.name}", on).apply()
}
