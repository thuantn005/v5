package vn.lotto535.watcher

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import vn.lotto535.watcher.data.Prefs
import vn.lotto535.watcher.data.Repository
import vn.lotto535.watcher.databinding.ActivityMainBinding
import vn.lotto535.watcher.logic.ShareDrawMachine
import vn.lotto535.watcher.logic.ShareDrawMachine.Kind
import vn.lotto535.watcher.work.Notifier
import vn.lotto535.watcher.work.Scheduler
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

class MainActivity : AppCompatActivity() {

    private lateinit var b: ActivityMainBinding
    private lateinit var prefs: Prefs

    private val askNotify = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { render() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMainBinding.inflate(layoutInflater)
        setContentView(b.root)
        prefs = Prefs(this)
        Notifier.ensureChannels(this)

        b.btnRefresh.setOnClickListener { refreshNow() }
        b.btnTest.setOnClickListener { sendTestNotification() }
        b.btnBattery.setOnClickListener { openBatterySettings() }

        b.swScheduled.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.SCHEDULED, on) }
        b.swReminder.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.REMINDER, on) }
        b.swCancelled.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.CANCELLED, on) }
        b.swCompleted.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.COMPLETED, on) }
        b.swNewDraw.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.NEW_DRAW, on) }
        b.swScrapeFail.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.SCRAPE_FAIL, on) }

        Scheduler.ensureScheduled(this)
        requestNotificationPermissionIfNeeded()
        render()
        refreshNow()
    }

    override fun onResume() {
        super.onResume()
        render()
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            askNotify.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun notificationsAllowed(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED

    private fun refreshNow() {
        b.btnRefresh.isEnabled = false
        b.txtStatus.text = "Đang cào trang chính thức…"
        lifecycleScope.launch {
            val snap = runCatching { Repository.scrape() }.getOrNull()
            if (snap == null) {
                b.txtStatus.text = "Cào thất bại — kiểm tra kết nối mạng."
            } else {
                val state = prefs.loadState()
                val events = ShareDrawMachine.check(
                    state, snap.jackpotVnd,
                    snap.latestDraw?.drawId ?: snap.jackpotDrawId,
                    snap.latestDraw?.drawDate,
                    prefs.jackpotHistory(),
                )
                prefs.saveState(state)
                snap.jackpotVnd?.let { prefs.pushJackpot(it); prefs.lastJackpot = it }
                snap.latestDraw?.let {
                    prefs.lastDrawId = it.drawId
                    prefs.lastDrawText = "#${it.drawId} — ${it.pretty()}"
                }
                prefs.lastSource = listOfNotNull(
                    snap.jackpotSource?.let { "pot: $it" },
                    snap.drawSource?.let { "số: $it" },
                ).joinToString(" · ").ifEmpty { "không nguồn nào trả lời" }
                prefs.lastCheckEpoch = System.currentTimeMillis()
                if (snap.jackpotVnd != null || snap.latestDraw != null) {
                    prefs.lastSuccessEpoch = System.currentTimeMillis()
                }

                var id = 5_000
                for (e in events) if (prefs.isEnabled(e.kind)) Notifier.show(this@MainActivity, e, id++)

                if (snap.errors.isNotEmpty()) {
                    b.txtErrors.text = "Nguồn lỗi:\n" + snap.errors.joinToString("\n") { "· $it" }
                    b.txtErrors.visibility = android.view.View.VISIBLE
                } else {
                    b.txtErrors.visibility = android.view.View.GONE
                }
            }
            b.btnRefresh.isEnabled = true
            render()
        }
    }

    private fun sendTestNotification() {
        Notifier.show(this, ShareDrawMachine.Event(
            Kind.REMINDER,
            "🔔 Thử thông báo — Lotto 5/35",
            "Nếu bạn thấy dòng này thì thông báo đã chạy đúng. Thông báo thật về " +
                "kỳ chia giải sẽ hiện y như vậy.",
            urgent = true,
        ), 9_999)
    }

    /**
     * Tối ưu hoá pin là lý do phổ biến nhất khiến công việc nền bị bóp chết —
     * nhất là trên Xiaomi/Oppo/Vivo/Samsung. Đưa thẳng người dùng tới đúng
     * màn hình cài đặt thay vì bắt họ tự mò.
     */
    private fun openBatterySettings() {
        val intents = listOf(
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                .setData(Uri.parse("package:$packageName")),
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
        )
        for (i in intents) {
            if (i.resolveActivity(packageManager) != null) { startActivity(i); return }
        }
    }

    private fun render() {
        val state = prefs.loadState()

        b.txtJackpot.text = ShareDrawMachine.fmt(prefs.lastJackpot.takeIf { it > 0 })

        val shareDate = state.shareDate
        if (state.pending && shareDate != null) {
            val d = runCatching { LocalDate.parse(shareDate) }.getOrNull()
            val today = ShareDrawMachine.todayVn()
            b.txtShare.text = when {
                d == null -> "Trạng thái hỏng — sẽ tự đặt lại ở lần cào sau"
                d == today -> "🔔 TỐI NAY 21:00 là kỳ CHIA GIẢI"
                d.isAfter(today) -> "📅 Kỳ chia giải: 21:00 ngày " +
                    "%02d/%02d/%d (còn %d ngày)".format(
                        d.dayOfMonth, d.monthValue, d.year, d.toEpochDay() - today.toEpochDay())
                else -> "Kỳ chia giải ${shareDate} đã qua — đang chờ xác nhận pot"
            }
            b.txtSharePeak.text = "Pot đỉnh chu kỳ này: ${ShareDrawMachine.fmt(state.peakJackpot)}" +
                (state.triggerDrawId?.let { "  ·  vượt 12 tỷ ở kỳ #$it" } ?: "")
            b.txtSharePeak.visibility = android.view.View.VISIBLE
        } else {
            val pot = prefs.lastJackpot
            val need = ShareDrawMachine.THRESHOLD_VND - pot
            b.txtShare.text = if (pot <= 0) "Chưa có dữ liệu Độc Đắc"
            else if (need > 0) "Chưa có kỳ chia giải — còn thiếu ${ShareDrawMachine.fmt(need)} " +
                "để vượt mốc 12 tỷ"
            else "Pot đã trên 12 tỷ — kỳ chia giải sẽ được xác định sau kỳ quay tới"
            b.txtSharePeak.visibility = android.view.View.GONE
        }

        b.txtDraw.text = prefs.lastDrawText
        b.txtSource.text = prefs.lastSource
        b.txtStatus.text = prefs.lastStatus
        b.txtLastCheck.text = prefs.lastCheckEpoch.takeIf { it > 0 }?.let {
            "Lần cào gần nhất: " + DateTimeFormatter.ofPattern("HH:mm dd/MM/yyyy")
                .format(Instant.ofEpochMilli(it).atZone(ZoneId.of("Asia/Ho_Chi_Minh"))) +
                " (giờ VN)"
        } ?: "Chưa cào lần nào"

        b.txtPermWarn.visibility =
            if (notificationsAllowed()) android.view.View.GONE else android.view.View.VISIBLE

        b.swScheduled.isChecked = prefs.isEnabled(Kind.SCHEDULED)
        b.swReminder.isChecked = prefs.isEnabled(Kind.REMINDER)
        b.swCancelled.isChecked = prefs.isEnabled(Kind.CANCELLED)
        b.swCompleted.isChecked = prefs.isEnabled(Kind.COMPLETED)
        b.swNewDraw.isChecked = prefs.isEnabled(Kind.NEW_DRAW)
        b.swScrapeFail.isChecked = prefs.isEnabled(Kind.SCRAPE_FAIL)
        val (nextAt, _) = Scheduler.nextSlot()
        b.txtInterval.text = "Tự cào lúc ${Scheduler.describe()} (giờ VN) · " +
            "lần tới %02d:%02d %02d/%02d".format(
                nextAt.hour, nextAt.minute, nextAt.dayOfMonth, nextAt.monthValue)
    }
}
