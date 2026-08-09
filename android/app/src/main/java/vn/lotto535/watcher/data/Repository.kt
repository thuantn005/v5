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
     * Hai loại dữ liệu, hai mức tin cậy khác nhau — nên lấy theo hai đường:
     *
     *  * ĐỘC ĐẮC ← trang chính thức trước. Parser tiền là bản cổng nguyên văn
     *    từ Python đã chạy thật, đối chiếu khớp 10/10 ca. Tin được.
     *
     *  * DÃY SỐ ← data.json của pipeline TRƯỚC, cào HTML chỉ để đối chiếu.
     *    Parser số dò bằng regex trên HTML chưa từng kiểm chứng với trang thật,
     *    và đã đo được nó nuốt ngày tháng thành số xổ số. Còn data.json thì đã
     *    qua kiểm định chéo nhiều nguồn của pipeline.
     *
     * Khi cả hai đều có số mà LỆCH nhau, tin data.json và ghi lại xung đột —
     * hiện số sai còn tệ hơn không hiện số nào.
     */
    suspend fun scrape(): Snapshot = withContext(Dispatchers.IO) {
        var jackpot: Long? = null
        var jackpotKy: String? = null
        var jackpotSrc: String? = null
        var trustedDraw: Draw? = null
        var scrapedDraw: Draw? = null
        var scrapedFrom: String? = null
        val errors = ArrayList<String>()

        // 1) Dãy số từ nguồn đã kiểm định chéo.
        try {
            trustedDraw = DrawParser.parsePagesJson(fetch(Sources.PAGES_DATA))
        } catch (e: Exception) {
            errors.add("pages/data.json: ${e.message}")
        }

        // 2) Độc Đắc từ trang chính thức, kèm cào số để đối chiếu.
        for (url in Sources.OFFICIAL + Sources.MIRRORS) {
            if (jackpot != null && scrapedDraw != null) break
            val host = runCatching { URL(url).host }.getOrDefault(url)
            try {
                val html = fetch(url)
                if (scrapedDraw == null) {
                    DrawParser.parseLatest(html)?.let { scrapedDraw = it; scrapedFrom = host }
                }
                if (jackpot == null) {
                    val ky = trustedDraw?.drawId ?: scrapedDraw?.drawId
                    val r = JackpotParser.extract(html, ky)
                    if (r.amountVnd != null) {
                        jackpot = r.amountVnd; jackpotKy = r.drawId; jackpotSrc = host
                    }
                }
            } catch (e: Exception) {
                errors.add("$host: ${e.message}")
                Log.w(TAG, "nguồn lỗi $url", e)
            }
        }

        // 3) Quyết định dãy số nào được hiển thị.
        var draw = trustedDraw
        var drawSrc: String? = if (trustedDraw != null) "github pages" else null
        val s = scrapedDraw
        if (s != null) {
            if (trustedDraw == null) {
                draw = s; drawSrc = scrapedFrom          // không có gì để đối chiếu
            } else if (s.drawId == trustedDraw.drawId) {
                if (s.numbers == trustedDraw.numbers && s.special == trustedDraw.special) {
                    drawSrc = "$scrapedFrom + github pages (khớp)"
                } else {
                    errors.add("LỆCH kỳ #${s.drawId}: $scrapedFrom cho ${s.pretty()}, " +
                        "pages cho ${trustedDraw.pretty()} → dùng pages")
                }
            } else if (s.drawId > trustedDraw.drawId) {
                // Kỳ mới hơn pages chưa kịp công bố. Dùng nhưng nói rõ là chưa
                // đối chiếu được với nguồn nào khác.
                draw = s; drawSrc = "$scrapedFrom (chưa đối chiếu)"
            }
        }

        // 4) Độc Đắc dự phòng.
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
