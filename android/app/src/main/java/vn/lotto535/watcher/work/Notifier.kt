package vn.lotto535.watcher.work

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import vn.lotto535.watcher.MainActivity
import vn.lotto535.watcher.R
import vn.lotto535.watcher.logic.ShareDrawMachine.Event

object Notifier {

    private const val CH_URGENT = "share_draw_urgent"
    private const val CH_INFO = "share_draw_info"

    fun ensureChannels(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CH_URGENT, "Kỳ chia giải Độc Đắc",
                NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Báo khi đã xác định và khi ĐẾN kỳ chia giải Độc Đắc."
            })
        nm.createNotificationChannel(
            NotificationChannel(CH_INFO, "Thông tin khác",
                NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "Kết quả kỳ mới, huỷ/hoàn tất chia giải, lỗi tra cứu."
            })
    }

    fun show(ctx: Context, event: Event, id: Int) {
        ensureChannels(ctx)
        val open = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val n = NotificationCompat.Builder(ctx, if (event.urgent) CH_URGENT else CH_INFO)
            .setSmallIcon(R.drawable.ic_stat_lotto)
            .setContentTitle(event.title)
            .setContentText(event.message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(event.message))
            .setPriority(if (event.urgent) NotificationCompat.PRIORITY_MAX
                         else NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setContentIntent(open)
            .build()
        try {
            NotificationManagerCompat.from(ctx).notify(id, n)
        } catch (e: SecurityException) {
            // Người dùng chưa cấp quyền POST_NOTIFICATIONS — màn hình chính có
            // nút xin quyền, ở đây chỉ cần không làm sập worker.
        }
    }
}
