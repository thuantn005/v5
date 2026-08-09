package vn.lotto535.watcher.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import vn.lotto535.watcher.data.Prefs
import vn.lotto535.watcher.data.Repository
import vn.lotto535.watcher.logic.ShareDrawMachine
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

/**
 * Một lần cào: lấy dữ liệu → chạy máy trạng thái chia giải → bắn thông báo →
 * hẹn lần kế tiếp.
 *
 * Lịch nằm ở [Scheduler]: ba mốc bám giờ quay, thử lại chỉ khi kỳ mới chưa về.
 * Worker này chỉ quyết định hai việc: có nên bỏ qua lần chạy này không, và có
 * cần hẹn thử lại không.
 */
class WatchWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        val reason = inputData.getString(Scheduler.KEY_REASON) ?: "slot"
        val expectsNewDraw = inputData.getBoolean(Scheduler.KEY_EXPECTS_DRAW, false)

        // Lưới an toàn chỉ tồn tại để hồi sinh chuỗi hẹn giờ. Nếu chuỗi vẫn
        // chạy tốt thì nó không có việc gì làm — bỏ qua để khỏi cào thừa.
        if (reason == "safety") {
            val ageMs = System.currentTimeMillis() - prefs.lastSuccessEpoch
            if (prefs.lastSuccessEpoch > 0 && ageMs < 4 * 60 * 60 * 1000L) {
                Scheduler.scheduleNextSlot(applicationContext)
                return Result.success()
            }
        }

        val knownDrawBefore = prefs.lastDrawId

        val snap = try {
            Repository.scrape()
        } catch (e: Exception) {
            prefs.lastStatus = "Lỗi cào: ${e.message}"
            return Result.retry()          // WorkManager tự lùi dần, vẫn chờ có mạng
        }

        val state = prefs.loadState()
        val events = ShareDrawMachine.check(
            state = state,
            jackpotVnd = snap.jackpotVnd,
            lastDrawId = snap.latestDraw?.drawId ?: snap.jackpotDrawId,
            lastDrawDate = snap.latestDraw?.drawDate,
            recentJackpots = prefs.jackpotHistory(),
        )
        prefs.saveState(state)

        val newDraw = snap.latestDraw
        val gotNewDraw = newDraw != null && newDraw.drawId != knownDrawBefore

        val allEvents = events.toMutableList()
        if (gotNewDraw && knownDrawBefore != null) {
            allEvents.add(ShareDrawMachine.Event(
                ShareDrawMachine.Kind.NEW_DRAW,
                "🎲 Kết quả kỳ #${newDraw!!.drawId}",
                "${newDraw.pretty()}\nĐộc Đắc: ${ShareDrawMachine.fmt(snap.jackpotVnd)}",
            ))
        }
        if (newDraw != null) prefs.lastDrawId = newDraw.drawId
        snap.jackpotVnd?.let { prefs.pushJackpot(it); prefs.lastJackpot = it }

        var id = 4_000
        for (e in allEvents) {
            if (prefs.isEnabled(e.kind)) Notifier.show(applicationContext, e, id++)
        }

        val now = ZonedDateTime.now(ShareDrawMachine.VN_ZONE)
        val ok = snap.jackpotVnd != null || newDraw != null
        prefs.lastCheckEpoch = System.currentTimeMillis()
        if (ok) prefs.lastSuccessEpoch = System.currentTimeMillis()
        prefs.lastDrawText = newDraw?.let { "#${it.drawId} — ${it.pretty()}" }
            ?: prefs.lastDrawText
        prefs.lastSource = listOfNotNull(
            snap.jackpotSource?.let { "pot: $it" },
            snap.drawSource?.let { "số: $it" },
        ).joinToString(" · ").ifEmpty { "không nguồn nào trả lời" }
        prefs.lastStatus = if (ok)
            "Cập nhật ${now.format(TIME_FMT)} (giờ VN)"
        else
            "Không lấy được gì lúc ${now.format(TIME_FMT)} (giờ VN)"

        // Chỉ thử lại ở mốc quay và chỉ khi kỳ mới CHƯA về — trang hay cập nhật
        // trễ vài chục phút. Kỳ đã về rồi thì thử lại là cào thừa.
        if (expectsNewDraw && !gotNewDraw) {
            if (prefs.retryCount < Scheduler.MAX_RETRIES) {
                prefs.retryCount = prefs.retryCount + 1
                Scheduler.scheduleRetry(applicationContext)
            } else {
                prefs.retryCount = 0
            }
        } else if (gotNewDraw) {
            prefs.retryCount = 0
        }

        // Luôn hẹn mốc kế tiếp — chuỗi tự nối, không phụ thuộc periodic work.
        Scheduler.scheduleNextSlot(applicationContext)

        return if (ok) Result.success() else Result.retry()
    }

    companion object {
        private val TIME_FMT: DateTimeFormatter =
            DateTimeFormatter.ofPattern("HH:mm dd/MM/yyyy")
    }
}
