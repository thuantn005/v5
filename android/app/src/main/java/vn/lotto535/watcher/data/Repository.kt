package vn.lotto535.watcher.data

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL
import java.util.zip.GZIPInputStream

/** Kết quả một lần cào: pot + kỳ mới nhất + nguồn nào đã trả lời. */
data class Snapshot(
    val jackpotVnd: Long?,
    val jackpotDrawId: String?,
    val latestDraw: Draw?,
    /** MỌI kỳ đọc được trên trang, tăng dần — để không bỏ sót kỳ giữa. */
    val draws: List<Draw>,
    val jackpotSource: String?,
    val drawSource: String?,
    val errors: List<String>,
)

object Repository {

    private const val TAG = "Lotto535"
    private const val TIMEOUT_MS = 20_000

    private fun fetch(url: String): String {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", Sources.USER_AGENT)
            setRequestProperty("Accept-Language", Sources.ACCEPT_LANGUAGE)
            setRequestProperty("Accept", "text/html,application/json;q=0.9,*/*;q=0.8")
            setRequestProperty("Accept-Encoding", "gzip")
        }
        try {
            val code = conn.responseCode
            if (code !in 200..299) throw RuntimeException("HTTP $code")
            val raw = conn.inputStream
            val stream = if (conn.contentEncoding?.contains("gzip", true) == true)
                GZIPInputStream(raw) else raw
            return stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            conn.disconnect()
        }
    }

    /**
     * Cào CHỈ trang chính thức (mirror chỉ chạy khi người dùng bật).
     *
     * Không còn nguồn thứ hai để đối chiếu, nên quy tắc là: dữ liệu nào không
     * chắc thì KHÔNG trả về. Thà app hiện "không đọc được dãy số" còn hơn hiện
     * một dãy số bịa — lỗi trước đây đúng là kiểu đó.
     *
     * @param allowMirrors bật nguồn dự phòng khi mạng không vào được vietlott.vn
     */
    suspend fun scrape(allowMirrors: Boolean = false): Snapshot = withContext(Dispatchers.IO) {
        var jackpot: Long? = null
        var jackpotKy: String? = null
        var jackpotSrc: String? = null
        var draw: Draw? = null
        var draws: List<Draw> = emptyList()
        var drawSrc: String? = null
        val errors = ArrayList<String>()

        val urls = if (allowMirrors) Sources.OFFICIAL + Sources.MIRRORS else Sources.OFFICIAL

        for (url in urls) {
            if (jackpot != null && draw != null) break
            val host = runCatching { URL(url).host }.getOrDefault(url)
            try {
                val html = fetch(url)

                if (draw == null) {
                    val found = DrawParser.parseAll(html)
                    if (found.isNotEmpty()) {
                        draws = found
                        draw = found.last()
                        drawSrc = host
                    } else {
                        // Nói rõ là KHÔNG ĐỌC ĐƯỢC, chứ không im lặng bỏ qua —
                        // im lặng khiến số cũ nằm lại trên màn hình như thể mới.
                        errors.add("$host: tải được trang nhưng không đọc chắc chắn được dãy số")
                    }
                }

                if (jackpot == null) {
                    val r = JackpotParser.extract(html, draw?.drawId)
                    if (r.amountVnd != null) {
                        jackpot = r.amountVnd; jackpotKy = r.drawId; jackpotSrc = host
                    }
                }
            } catch (e: Exception) {
                errors.add("$host: ${e.message}")
                Log.w(TAG, "nguồn lỗi $url", e)
            }
        }

        if (jackpot == null && draw == null && errors.isEmpty()) {
            errors.add("vietlott.vn: không trả về dữ liệu dùng được")
        }

        Snapshot(jackpot, jackpotKy, draw, draws, jackpotSrc, drawSrc, errors)
    }

    /**
     * Tải trọn bộ lịch sử để VÁ những kỳ bị thiếu.
     *
     * Chỉ gọi khi app phát hiện lỗ hổng — không dùng cho kỳ mới hay Độc Đắc,
     * hai thứ đó vẫn phải đến từ trang chính thức. Trang chính thức chỉ đăng
     * kỳ gần nhất nên tự nó không vá được quá khứ.
     */
    suspend fun fetchHistory(): List<Draw> = withContext(Dispatchers.IO) {
        try {
            DrawParser.parseHistoryJson(fetch(Sources.PAGES_HISTORY))
        } catch (e: Exception) {
            Log.w(TAG, "không tải được lịch sử vá", e)
            emptyList()
        }
    }
}
