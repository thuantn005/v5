package vn.lotto535.watcher.data

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Nhận tin từ ntfy.sh/lotto535-thuan — cùng topic mà pipeline trên server đẩy.
 *
 * Vì sao POLL chứ không mở kết nối thường trực (SSE):
 *   - SSE trên Android cần foreground service chạy suốt, ngốn pin, và hay bị
 *     ROM Xiaomi/Oppo giết.
 *   - App này vốn đã thức dậy theo lịch (08:00 / 13:10 / 21:10 + thử lại), nên
 *     poll kèm theo mỗi lần thức là gần như miễn phí.
 *   - Đánh đổi: tin ntfy có thể trễ tới lần cào kế tiếp. Chấp nhận được, vì
 *     thông báo chia giải tính theo NGÀY. Ai cần tức thời thì cài app ntfy
 *     chính thức, subscribe cùng topic — hai đường không xung đột.
 *
 * ntfy giữ tin 12 giờ ở gói miễn phí, nên poll thưa hơn 12h có thể mất tin cũ;
 * lịch dày nhất của app là vài giờ/lần nên trong ngưỡng an toàn.
 */
object Ntfy {

    const val DEFAULT_TOPIC = "lotto535-thuan"
    private const val TIMEOUT_MS = 20_000
    private const val TAG = "Lotto535"

    data class Message(val id: String, val time: Long, val title: String?, val body: String)

    /**
     * Lấy các tin MỚI kể từ mốc `sinceEpochSec` (giây). Trả (danh sách tin,
     * mốc thời gian mới nhất) để người gọi lưu lại làm con trỏ.
     *
     * Dùng endpoint poll: ntfy.sh/<topic>/json?poll=1&since=<epoch>. Mỗi dòng
     * là một JSON; chỉ nhận event == "message".
     */
    suspend fun poll(topic: String, sinceEpochSec: Long): Pair<List<Message>, Long> =
        withContext(Dispatchers.IO) {
            val since = if (sinceEpochSec > 0) sinceEpochSec.toString() else "12h"
            val url = "https://ntfy.sh/$topic/json?poll=1&since=$since"
            val out = ArrayList<Message>()
            var newest = sinceEpochSec
            try {
                val conn = (URL(url).openConnection() as HttpURLConnection).apply {
                    connectTimeout = TIMEOUT_MS
                    readTimeout = TIMEOUT_MS
                    setRequestProperty("User-Agent", Sources.USER_AGENT)
                }
                if (conn.responseCode !in 200..299) {
                    return@withContext Pair(emptyList(), sinceEpochSec)
                }
                conn.inputStream.bufferedReader(Charsets.UTF_8).useLines { lines ->
                    for (line in lines) {
                        val s = line.trim()
                        if (s.isEmpty()) continue
                        try {
                            val o = JSONObject(s)
                            if (o.optString("event") != "message") continue
                            val t = o.optLong("time", 0L)
                            val id = o.optString("id")
                            val body = o.optString("message")
                            if (body.isEmpty()) continue
                            out.add(Message(id, t, o.optString("title").ifEmpty { null }, body))
                            if (t > newest) newest = t
                        } catch (e: Exception) {
                            // dòng hỏng — bỏ qua, đừng phá cả lần poll
                        }
                    }
                }
                conn.disconnect()
            } catch (e: Exception) {
                Log.w(TAG, "ntfy poll lỗi", e)
                return@withContext Pair(emptyList(), sinceEpochSec)
            }
            Pair(out, newest)
        }
}
