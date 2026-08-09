package vn.lotto535.watcher.work

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.time.Duration
import java.time.LocalTime
import java.time.ZonedDateTime
import java.util.concurrent.TimeUnit
import vn.lotto535.watcher.logic.ShareDrawMachine.VN_ZONE

/**
 * Lịch cào: BÁM MỐC GIỜ thay vì quét đều cả ngày.
 *
 * Bản đầu chạy 30 phút/lần — 48 lần/ngày, phần lớn rơi vào lúc chẳng có gì
 * thay đổi (Lotto 5/35 chỉ quay 13:00 và 21:00). Ở đây chỉ giữ ba mốc, cộng
 * thử lại KHI CẦN:
 *
 *   08:00  không đợi kỳ mới — mốc này để nhắc "HÔM NAY là kỳ chia giải" từ
 *          sáng, người chơi còn kịp mua vé trước 21:00.
 *   13:10  ngay sau kỳ quay trưa.
 *   21:10  ngay sau kỳ quay tối.
 *
 * Ở hai mốc quay, nếu chưa thấy kỳ mới (trang cập nhật trễ) thì hẹn thử lại
 * sau 25 phút, TỐI ĐA 2 lần. Có kỳ mới rồi thì không thử lại nữa.
 *
 *   ngày yên ả : 3 lần
 *   ngày xấu   : 7 lần (3 mốc + 4 lần thử lại)
 *
 * Lưới an toàn 6 giờ/lần vớt trường hợp chuỗi hẹn giờ bị ROM cắt; nó tự bỏ
 * qua nếu vừa cào thành công trong 4 giờ qua, nên gần như không tốn gì.
 *
 * MẤT MẠNG THÌ SAO? Mọi yêu cầu mang ràng buộc NetworkType.CONNECTED, nên
 * WorkManager KHÔNG bỏ qua mốc đó — nó giữ việc ở trạng thái chờ và chạy ngay
 * khi mạng trở lại, dù là ba tiếng sau. Cào lỗi giữa chừng thì Result.retry()
 * cho lùi dần theo cấp số nhân, vẫn kèm đúng ràng buộc ấy.
 *
 * Ba lớp để một mốc không bị mất:
 *   1. ràng buộc mạng  — hoãn chứ không bỏ
 *   2. KEEP khi mở app — không giẫm lên lần cào đang chờ (xem scheduleNextSlot)
 *   3. lưới an toàn 6h — hồi sinh chuỗi nếu ROM cắt mất
 */
object Scheduler {

    data class Slot(val time: LocalTime, val expectsNewDraw: Boolean)

    val SLOTS = listOf(
        Slot(LocalTime.of(8, 0), false),
        Slot(LocalTime.of(13, 10), true),
        Slot(LocalTime.of(21, 10), true),
    )

    const val MAX_RETRIES = 2
    const val RETRY_MINUTES = 25L
    private const val SAFETY_HOURS = 6L

    const val WORK_SLOT = "lotto535-slot"
    const val WORK_RETRY = "lotto535-retry"
    const val WORK_SAFETY = "lotto535-safety"

    const val KEY_REASON = "reason"
    const val KEY_EXPECTS_DRAW = "expects_draw"

    private fun constraints() = Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED)
        .build()

    /** Mốc kế tiếp tính theo GIỜ VN, kể cả khi máy đang ở múi giờ khác. */
    fun nextSlot(now: ZonedDateTime = ZonedDateTime.now(VN_ZONE)): Pair<ZonedDateTime, Slot> {
        for (s in SLOTS) {
            val at = now.with(s.time).withSecond(0).withNano(0)
            if (at.isAfter(now)) return at to s
        }
        val first = SLOTS.first()
        return now.plusDays(1).with(first.time).withSecond(0).withNano(0) to first
    }

    /**
     * Hẹn lần cào theo mốc kế tiếp.
     *
     * @param replace true khi gọi từ cuối một lần chạy — phải thay thế để nối
     *   chuỗi. false khi gọi lúc mở app / khởi động máy: nếu đang có một mốc
     *   BỊ TREO CHỜ MẠNG thì phải GIỮ NGUYÊN nó. Trước đây chỗ này luôn dùng
     *   REPLACE, nên mở app trong lúc mất mạng sẽ xoá mất lần cào đang chờ và
     *   kỳ quay đó không bao giờ được kiểm tra.
     */
    fun scheduleNextSlot(ctx: Context, replace: Boolean = true) {
        val now = ZonedDateTime.now(VN_ZONE)
        val (at, slot) = nextSlot(now)
        val delay = Duration.between(now, at).toMillis().coerceAtLeast(1_000L)

        val req = OneTimeWorkRequestBuilder<WatchWorker>()
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .setConstraints(constraints())
            .setInputData(Data.Builder()
                .putString(KEY_REASON, "slot")
                .putBoolean(KEY_EXPECTS_DRAW, slot.expectsNewDraw)
                .build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.MINUTES)
            .build()

        WorkManager.getInstance(ctx).enqueueUniqueWork(
            WORK_SLOT,
            if (replace) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.KEEP,
            req,
        )
    }

    /** Thử lại sau khi một mốc quay chưa thấy kỳ mới. */
    fun scheduleRetry(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<WatchWorker>()
            .setInitialDelay(RETRY_MINUTES, TimeUnit.MINUTES)
            .setConstraints(constraints())
            .setInputData(Data.Builder()
                .putString(KEY_REASON, "retry")
                .putBoolean(KEY_EXPECTS_DRAW, true)
                .build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.MINUTES)
            .build()

        WorkManager.getInstance(ctx)
            .enqueueUniqueWork(WORK_RETRY, ExistingWorkPolicy.REPLACE, req)
    }

    /** Lưới an toàn — chỉ để hồi sinh chuỗi hẹn giờ nếu nó bị cắt. */
    fun scheduleSafetyNet(ctx: Context) {
        val req = PeriodicWorkRequestBuilder<WatchWorker>(SAFETY_HOURS, TimeUnit.HOURS)
            .setConstraints(constraints())
            .setInputData(Data.Builder()
                .putString(KEY_REASON, "safety")
                .putBoolean(KEY_EXPECTS_DRAW, false)
                .build())
            .build()

        WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(
            WORK_SAFETY, ExistingPeriodicWorkPolicy.UPDATE, req,
        )
    }

    /**
     * Gọi khi mở app và sau khi khởi động lại máy. Dùng KEEP để không giẫm lên
     * lần cào đang chờ mạng.
     */
    fun ensureScheduled(ctx: Context) {
        scheduleNextSlot(ctx, replace = false)
        scheduleSafetyNet(ctx)
    }

    /** Mô tả lịch cho màn hình chính. */
    fun describe(): String =
        SLOTS.joinToString(" · ") { "%02d:%02d".format(it.time.hour, it.time.minute) }
}
