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
import vn.lotto535.watcher.logic.AntiCrowd
import vn.lotto535.watcher.logic.PredictionAudit
import vn.lotto535.watcher.logic.Predictor
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
    private var historyExpanded = false

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
        b.btnHistoryToggle.setOnClickListener {
            historyExpanded = !historyExpanded
            renderHistory()
        }
        b.btnBackfill.setOnClickListener { backfillNow() }
        b.btnWinnerCounts.setOnClickListener { fetchWinnerCountsNow() }

        b.swScheduled.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.SCHEDULED, on) }
        b.swReminder.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.REMINDER, on) }
        b.swCancelled.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.CANCELLED, on) }
        b.swCompleted.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.COMPLETED, on) }
        b.swNewDraw.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.NEW_DRAW, on) }
        b.swScrapeFail.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.SCRAPE_FAIL, on) }
        b.swMissed.setOnCheckedChangeListener { _, on -> prefs.setEnabled(Kind.MISSED, on) }
        b.swMirrors.setOnCheckedChangeListener { _, on ->
            prefs.useMirrors = on
            if (on) refreshNow()
        }
        b.swNtfy.setOnCheckedChangeListener { _, on ->
            prefs.ntfyEnabled = on
            if (on) pollNtfyNow()
        }

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
            val snap = runCatching { Repository.scrape(prefs.useMirrors) }.getOrNull()
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
                prefs.addDraws(snap.draws)
                if (snap.latestDraw != null) {
                    prefs.lastDrawId = snap.latestDraw.drawId
                    prefs.lastDrawText = "#${snap.latestDraw.drawId} — ${snap.latestDraw.pretty()}"
                } else {
                    // Không đọc được thì NÓI RÕ, đừng để số cũ nằm lại như thể mới.
                    prefs.lastDrawText = "⚠️ Không đọc được dãy số từ trang chính thức"
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

    /**
     * Dự đoán kỳ tới, tính ngay trên máy từ lịch sử đã lưu — không cần mạng.
     */
    private fun renderPrediction() {
        b.predictBox.removeAllViews()
        val hist = prefs.history()
        val lastId = hist.maxOfOrNull { it.drawId }?.toIntOrNull()

        if (hist.isEmpty() || lastId == null) {
            b.txtPredictTitle.text = "Dự đoán kỳ tới"
            b.txtPredictNote.text = "Cần có lịch sử trước. Bấm \"Tải bổ sung lịch " +
                "sử còn thiếu\" hoặc chờ lần cào đầu tiên."
            return
        }

        val nextId = "%05d".format(lastId + 1)
        b.txtPredictTitle.text = "Dự đoán kỳ tới — #$nextId"

        for (t in Predictor.predict(hist, nextId, count = 5)) {
            val tv = android.widget.TextView(this).apply {
                text = t.label()
                textSize = 14f
                typeface = android.graphics.Typeface.MONOSPACE
                setPadding(0, 6, 0, 6)
            }
            b.predictBox.addView(tv)
        }

        b.txtPredictNote.text =
            "Kết hợp tần suất gần đây + toàn lịch sử + số kỳ vắng mặt, bốc ngẫu " +
            "nhiên theo trọng số, tái lập được từ mã kỳ. Backtest 600 kỳ với 19 " +
            "model: KHÔNG công thức nào vượt ngẫu nhiên thuần — vé ngẫu nhiên còn " +
            "về nhì. Mọi vé đều 1/324.632 (J2) và 1/3.895.584 (J1). Đây là cách " +
            "chọn số, không phải cách tăng cơ hội."

        renderAntiCrowd(nextId)
    }

    /**
     * Vé NGƯỢC ĐÁM ĐÔNG + kết quả đo thiên lệch từ bảng số người trúng.
     * Đây là phần DUY NHẤT tác động lên số tiền nhận được (giảm chia giải),
     * chứ không phải lên xác suất trúng.
     */
    private fun renderAntiCrowd(nextId: String) {
        b.antiCrowdBox.removeAllViews()
        val rows = prefs.winnerCounts()

        for (t in AntiCrowd.generate(nextId, 5, rows)) {
            val tv = android.widget.TextView(this).apply {
                text = t.label()
                textSize = 14f
                typeface = android.graphics.Typeface.MONOSPACE
                setPadding(0, 6, 0, 6)
            }
            b.antiCrowdBox.addView(tv)
        }

        val bias = vn.lotto535.watcher.data.CrowdBias.analyze(rows)
        b.txtAntiCrowdNote.text = when {
            bias == null ->
                "Chưa gom được bảng số người trúng nào. App tự cào từ minhchinh " +
                "mỗi kỳ; bấm \"Cào bảng số người trúng\" để lấy ngay. Tạm dùng " +
                "quy luật chung: né vùng ngày sinh (≤31), dãy liên tiếp, cấp số cộng."
            bias.significant -> {
                val pct = ((1.0 / 12 - bias.pickedFraction) / (1.0 / 12) * 100)
                "ĐO TỪ ${bias.draws} kỳ: đám đông %s số ĐB đúng %.0f%% so với ngẫu nhiên "
                    .format(if (pct > 0) "né" else "dồn", kotlin.math.abs(pct)) +
                "(p=%.1e). Vé trên né vùng đám đông. XÁC SUẤT TRÚNG KHÔNG ĐỔI — chỉ giảm số người chia giải nếu trúng."
                    .format(bias.pValue)
            }
            else ->
                "Đã gom ${bias.draws} kỳ nhưng chưa đủ mạnh để kết luận (p=%.2f). "
                    .format(bias.pValue) +
                "Tạm dùng quy luật chung. Càng nhiều kỳ, bản đồ càng chính xác."
        }
    }

    /** Poll ntfy ngay để kéo tin server đã đẩy. */
    private fun pollNtfyNow() {
        lifecycleScope.launch {
            try {
                val (msgs, newest) = vn.lotto535.watcher.data.Ntfy.poll(
                    prefs.ntfyTopic, prefs.ntfySince)
                for (m in msgs) {
                    Notifier.showText(this@MainActivity,
                        m.title ?: "Lotto 5/35", m.body, 6_000 + (m.id.hashCode() and 0xFFF))
                }
                if (newest > prefs.ntfySince) prefs.ntfySince = newest
            } catch (e: Exception) { /* im lặng, sẽ thử lại lần cào sau */ }
        }
    }

    /** Cào bảng số người trúng ngay (thường app tự làm mỗi kỳ). */
    private fun fetchWinnerCountsNow() {
        b.btnWinnerCounts.isEnabled = false
        b.btnWinnerCounts.text = "Đang cào bảng…"
        lifecycleScope.launch {
            val wc = runCatching { Repository.fetchWinnerCounts() }.getOrNull()
            if (wc != null) prefs.addWinnerCounts(wc)
            val n = prefs.winnerCounts().size
            b.btnWinnerCounts.text = if (wc == null)
                "Không cào được bảng số người trúng"
            else
                "Đã có $n kỳ số người trúng"
            b.btnWinnerCounts.isEnabled = true
            val lastId = prefs.history().maxOfOrNull { it.drawId }?.toIntOrNull()
            if (lastId != null) renderAntiCrowd("%05d".format(lastId + 1))
        }
    }

    /** Tải trọn bộ lịch sử để vá những kỳ còn thiếu. */
    private fun backfillNow() {
        b.btnBackfill.isEnabled = false
        b.btnBackfill.text = "Đang tải lịch sử…"
        lifecycleScope.launch {
            val before = prefs.history().size
            val all = runCatching { Repository.fetchHistory() }.getOrDefault(emptyList())
            if (all.isNotEmpty()) prefs.addDraws(all)
            val after = prefs.history().size
            b.btnBackfill.text = if (all.isEmpty())
                "Không tải được lịch sử bổ sung"
            else
                "Đã bổ sung ${after - before} kỳ (tổng $after)"
            b.btnBackfill.isEnabled = true
            renderHistory()
            renderPrediction()
        }
    }

    /**
     * Bảng vàng: vé dự đoán từng kỳ quá khứ vs kết quả thật. Chạy trên máy,
     * backtest tiến (chỉ dùng quá khứ mỗi kỳ) nên trung thực.
     */
    private fun renderAudit() {
        b.auditBox.removeAllViews()
        val hist = prefs.history()
        if (hist.size < 40) {
            b.txtAuditSummary.text = "Cần thêm lịch sử để chấm (bấm \"Tải bổ sung lịch sử\")."
            b.txtAuditNote.text = ""
            return
        }
        val s = PredictionAudit.audit(hist)
        if (s.evaluated == 0) {
            b.txtAuditSummary.text = "Chưa chấm được kỳ nào."
            return
        }

        b.txtAuditSummary.text =
            "Chấm ${s.evaluated} kỳ · trúng nhiều nhất (best 5 vé): " +
            "%.3f số — ngẫu nhiên %.3f · trúng ĐB %.0f%% · J2 %d · J1 %d"
                .format(s.avgBestMainHits, s.avgBestMainRandom,
                        s.specialHitRate * 100, s.jackpot2, s.jackpot1)

        for (r in s.rows.take(25)) {
            val stars = "●".repeat(r.bestMainHits) + "○".repeat(5 - r.bestMainHits)
            val extra = buildString {
                if (r.specialHit) append(" +ĐB")
                if (r.jackpot2) append(" ★J2")
                if (r.jackpot1) append(" ★★J1")
            }
            val tv = android.widget.TextView(this).apply {
                text = "#${r.drawId}  $stars ${r.bestMainHits}/5$extra"
                textSize = 13f
                typeface = android.graphics.Typeface.MONOSPACE
                setPadding(0, 5, 0, 5)
            }
            b.auditBox.addView(tv)
        }

        val diff = s.avgBestMainHits - s.avgBestMainRandom
        b.txtAuditNote.text =
            "So công bằng: best-của-5-vé công thức vs best-của-5-vé NGẪU NHIÊN " +
            "(so với 0,7143 của 1 vé là sai). Chênh lệch %+.3f. ".format(diff) +
            "Trên ít kỳ, chênh này dao động và dễ trông như lợi thế; càng nhiều " +
            "kỳ càng co về 0 (đo 600 kỳ: +0,01). Không có lợi thế thật — mọi vé " +
            "vẫn 1/324.632 (J2), 1/3.895.584 (J1)."
    }

    /**
     * Lịch sử tích luỹ. Chỗ nào thủng mã kỳ thì hiện thẳng dòng "thiếu #…" —
     * lịch sử có lỗ mà trông liền mạch còn nguy hiểm hơn không có lịch sử.
     */
    private fun renderHistory() {
        val hist = prefs.history()          // đã sắp giảm dần theo mã kỳ
        b.historyBox.removeAllViews()

        if (hist.isEmpty()) {
            b.txtHistoryNote.text =
                "Chưa có kỳ nào. Lịch sử gom dần sau mỗi lần cào — trang chính " +
                "thức chỉ đăng kỳ gần nhất nên không tải về một lần được."
            return
        }
        b.txtHistoryNote.text = "${hist.size} kỳ đã ghi nhận (mới nhất trước)"

        val shown = if (historyExpanded) hist else hist.take(20)
        b.btnHistoryToggle.text =
            if (historyExpanded) "Thu gọn" else "Xem tất cả (${hist.size} kỳ)"
        b.btnHistoryToggle.visibility =
            if (hist.size > 20) android.view.View.VISIBLE else android.view.View.GONE
        for ((i, d) in shown.withIndex()) {
            addHistoryRow("#${d.drawId}  ${d.drawDate}   ${d.pretty()}", false)

            // Khoảng trống giữa kỳ này và kỳ kế tiếp trong danh sách.
            val next = shown.getOrNull(i + 1) ?: continue
            val a = d.drawId.toIntOrNull() ?: continue
            val bId = next.drawId.toIntOrNull() ?: continue
            if (a - bId > 1) {
                val missing = ((bId + 1) until a).joinToString(", ") { "#%05d".format(it) }
                addHistoryRow("⚠️ thiếu $missing", true)
            }
        }

    }

    private fun addHistoryRow(text: String, warn: Boolean) {
        val tv = android.widget.TextView(this).apply {
            this.text = text
            textSize = 13f
            typeface = android.graphics.Typeface.MONOSPACE
            setPadding(0, 6, 0, 6)
            if (warn) {
                setTextColor(0xFFC62828.toInt())
                typeface = android.graphics.Typeface.DEFAULT_BOLD
                textSize = 12f
            } else {
                alpha = 0.85f
            }
        }
        b.historyBox.addView(tv)
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

        renderHistory()
        renderPrediction()
        renderAudit()

        b.txtPermWarn.visibility =
            if (notificationsAllowed()) android.view.View.GONE else android.view.View.VISIBLE

        b.swScheduled.isChecked = prefs.isEnabled(Kind.SCHEDULED)
        b.swReminder.isChecked = prefs.isEnabled(Kind.REMINDER)
        b.swCancelled.isChecked = prefs.isEnabled(Kind.CANCELLED)
        b.swCompleted.isChecked = prefs.isEnabled(Kind.COMPLETED)
        b.swNewDraw.isChecked = prefs.isEnabled(Kind.NEW_DRAW)
        b.swScrapeFail.isChecked = prefs.isEnabled(Kind.SCRAPE_FAIL)
        b.swMirrors.isChecked = prefs.useMirrors
        b.swNtfy.isChecked = prefs.ntfyEnabled
        b.swMissed.isChecked = prefs.isEnabled(Kind.MISSED)
        val (nextAt, _) = Scheduler.nextSlot()
        b.txtInterval.text = "Tự cào lúc ${Scheduler.describe()} (giờ VN) · " +
            "lần tới %02d:%02d %02d/%02d".format(
                nextAt.hour, nextAt.minute, nextAt.dayOfMonth, nextAt.monthValue)
    }
}
