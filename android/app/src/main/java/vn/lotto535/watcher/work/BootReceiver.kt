package vn.lotto535.watcher.work

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * WorkManager tự khôi phục lịch sau khi khởi động lại máy, nhưng chỉ với công
 * việc nó còn giữ trong CSDL. Đặt lại lịch ở đây là lớp bảo hiểm rẻ tiền —
 * mất thông báo kỳ chia giải là mất hẳn, không lấy lại được.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED ||
            intent.action == Intent.ACTION_MY_PACKAGE_REPLACED
        ) {
            Scheduler.ensureScheduled(context)
        }
    }
}
