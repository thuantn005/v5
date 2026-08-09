package vn.lotto535.watcher.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import vn.lotto535.watcher.data.Prefs
import vn.lotto535.watcher.data.Repository
import vn.lotto535.watcher.logic.ShareDrawMachine
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

/**
 * Chạy nền: cào nguồn → chạy máy trạng thái → bắn thông báo.
 *
 * Dùng WorkManager chứ không phải AlarmManager: WorkManager sống sót qua khởi
 * động lại máy, tự hoãn khi mất mạng, và tuân thủ Doze thay vì bị hệ thống giết.
 * Đổi lại chu kỳ tối thiểu là 15 phút — thừa sức cho việc này, vì cảnh báo chia
 * giải tính theo NGÀY chứ không theo phút.
 */
class WatchWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        val snap = try {
            Repository.scrape()
        } catch (e: Exception) {
            prefs.lastStatus = "Lỗi cào: ${e.message}"
            return Result.retry()
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

        // Kỳ mới về — sự kiện riêng, không nằm trong máy trạng thái chia giải.
        val newDraw = snap.latestDraw
        val allEvents = events.toMutableList()
        if (newDraw != null && newDraw.drawId != prefs.lastDrawId) {
            if (prefs.lastDrawId != null) {
                allEvents.add(ShareDrawMachine.Event(
                    ShareDrawMachine.Kind.NEW_DRAW,
                    "🎲 Kết quả kỳ #${newDraw.drawId}",
                    "${newDraw.pretty()}\nĐộc Đắc: ${ShareDrawMachine.fmt(snap.jackpotVnd)}",
                ))
            }
            prefs.lastDrawId = newDraw.drawId
        }

        snap.jackpotVnd?.let { prefs.pushJackpot(it); prefs.lastJackpot = it }

        var id = 4_000
        for (e in allEvents) {
            if (prefs.isEnabled(e.kind)) Notifier.show(applicationContext, e, id++)
        }

        val now = ZonedDateTime.now(ShareDrawMachine.VN_ZONE)
        prefs.lastCheckEpoch = System.currentTimeMillis()
        prefs.lastDrawText = newDraw?.let { "#${it.drawId} — ${it.pretty()}" } ?: "—"
        prefs.lastSource = listOfNotNull(
            snap.jackpotSource?.let { "pot: $it" },
            snap.drawSource?.let { "số: $it" },
        ).joinToString(" · ").ifEmpty { "không nguồn nào trả lời" }
        prefs.lastStatus = if (snap.jackpotVnd == null && newDraw == null)
            "Không lấy được gì lúc ${now.format(TIME_FMT)} (giờ VN)"
        else
            "Cập nhật ${now.format(TIME_FMT)} (giờ VN)"

        return if (snap.jackpotVnd == null && newDraw == null) Result.retry() else Result.success()
    }

    companion object {
        private const val WORK_NAME = "lotto535-watch"
        private val TIME_FMT: DateTimeFormatter =
            DateTimeFormatter.ofPattern("HH:mm dd/MM/yyyy")

        fun schedule(ctx: Context, minutes: Int) {
            val req = PeriodicWorkRequestBuilder<WatchWorker>(
                minutes.coerceAtLeast(15).toLong(), TimeUnit.MINUTES,
            ).setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            ).build()

            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(
                WORK_NAME, ExistingPeriodicWorkPolicy.UPDATE, req,
            )
        }

        fun cancel(ctx: Context) {
            WorkManager.getInstance(ctx).cancelUniqueWork(WORK_NAME)
        }
    }
}
