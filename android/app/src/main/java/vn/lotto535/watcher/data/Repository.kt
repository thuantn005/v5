package vn.lotto535.watcher.data

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.zip.GZIPInputStream

/** Kết quả một lần cào: pot + kỳ mới nhất + nguồn nào đã trả lời. */
data class Snapshot(
    val jackpotVnd: Long?,
    val jackpotDrawId: String?,
    val latestDraw: Draw?,
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
     * Cào theo thứ tự: trang CHÍNH THỨC trước, rồi mirror, cuối cùng là dữ liệu
     * repo tự công bố. Dừng ngay khi có đủ (pot + kỳ), nhưng vẫn thử tiếp nếu
     * mới chỉ có một nửa.
     */
    suspend fun scrape(): Snapshot = withContext(Dispatchers.IO) {
        var jackpot: Long? = null
        var jackpotKy: String? = null
        var jackpotSrc: String? = null
        var draw: Draw? = null
        var drawSrc: String? = null
        val errors = ArrayList<String>()

        for (url in Sources.OFFICIAL + Sources.MIRRORS) {
            if (jackpot != null && draw != null) break
            val host = runCatching { URL(url).host }.getOrDefault(url)
            try {
                val html = fetch(url)
                if (draw == null) {
                    DrawParser.parseLatest(html)?.let { draw = it; drawSrc = host }
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

        // Dự phòng cuối — dữ liệu repo tự công bố.
        if (draw == null) {
            try {
                draw = DrawParser.parsePagesJson(fetch(Sources.PAGES_DATA))
                if (draw != null) drawSrc = "github pages"
            } catch (e: Exception) {
                errors.add("pages/data.json: ${e.message}")
            }
        }
        if (jackpot == null) {
            try {
                val o = JSONObject(fetch(Sources.PAGES_JACKPOT))
                val v = o.optLong("jackpot_vnd", 0L)
                if (v > 0) {
                    jackpot = v
                    jackpotKy = o.optString("draw_id").ifEmpty { null }
                    jackpotSrc = "github pages"
                }
            } catch (e: Exception) {
                errors.add("pages/jackpot.json: ${e.message}")
            }
        }

        Snapshot(jackpot, jackpotKy, draw, jackpotSrc, drawSrc, errors)
    }
}
