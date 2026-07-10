"""
run_pipeline.py
-----------------
Full automated pipeline, run twice daily by GitHub Actions:

  1. (data/all.csv already refreshed by fetch_data.py, a separate step)
  2. Auto-tune strategy parameters (tuning.py) -- only runs if >=7 days
     since the last tuning run; otherwise reuses state/tuned_params.json.
  3. Backtest every strategy honestly vs the exact random baseline
     (backtest_all.py) -> state/model_leaderboard.json.
  4. Calibrate the ensemble's notification threshold (ensemble_calibrate.py).
  5. Compute the Ensemble Voting prediction for the next draw.
  6. Check jackpot-sharing-round status + early "sắn kỳ chia giải" alert.
  7. Decide whether to notify via ntfy (high ensemble confidence OR
     jackpot-sharing round OR jackpot-threshold-crossing).
  8. Log the full prediction (ensemble + every individual strategy) to
     state/ensemble_log.jsonl.
  9. Resolve any previously-logged predictions whose target draw has now
     happened (multi_log.resolve_all()).
 10. Generate dashboard data (generate_dashboard_data.py) for GitHub Pages.
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone

from model import parse_draws
from ensemble import ensemble_predict, load_tuned_params
from jackpot_check import check_jackpot
from jackpot_watch import check_early_alert, check_scrape_alert, get_threshold_crossed_date
from references import compute_tickets as compute_references
from notify_ntfy import send as _ntfy_send_raw
from multi_log import append_prediction, resolve_all, load_log, _next_draw_id

import tuning
import backtest_all

DATA_PATH = "data/all.csv"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "lotto535-thuan")


def ntfy_send(*args, **kwargs):
    """Send an ntfy notification, but NEVER let a notification failure abort
    the pipeline. A transient ntfy.sh outage / rate-limit / network blip must
    not stop us from logging the prediction and resolving past results (both
    happen after the notify blocks). Log the error and carry on."""
    try:
        _ntfy_send_raw(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 -- notifications are best-effort
        print(f"WARNING: ntfy notification failed (continuing): {e}", file=sys.stderr)


def _predicted_numbers(entry: dict, label: str):
    """Return (main_list, special) that `label` predicted in this log entry."""
    if label == "ensemble":
        return entry["ensemble"]["main"], entry["ensemble"]["special"]
    if label.startswith("ref_"):
        r = (entry.get("references") or {}).get(label[len("ref_"):], {})
        return r.get("main"), r.get("special")
    pick = (entry.get("per_strategy") or {}).get(label, {})
    return pick.get("main"), pick.get("special")


def notify_perfect_wins(newly_resolved):
    """When any logged prediction for a just-resolved draw matched all 5 main
    numbers AND the special number, fire a celebratory ntfy. Runs off the
    entries resolve_all() reports as newly resolved, so each win alerts
    exactly once (the run its result first became available)."""
    for entry in newly_resolved:
        actual = entry.get("actual") or {}
        hits = entry.get("hits") or {}
        winners = [
            label for label, h in hits.items()
            if h and h.get("main_hits") == 5 and h.get("special_hit")
        ]
        if not winners:
            continue

        actual_main = "-".join(f"{n:02d}" for n in actual.get("main", []))
        actual_special = f"{actual.get('special'):02d}" if actual.get("special") is not None else "??"
        lines = []
        for label in winners:
            main, special = _predicted_numbers(entry, label)
            main_str = "-".join(f"{n:02d}" for n in (main or []))
            sp_str = f"{special:02d}" if special is not None else "??"
            lines.append(f"• {label}: {main_str} + {sp_str}")

        ntfy_send(
            NTFY_TOPIC,
            title="🏆 TRÚNG! Dự đoán khớp 5 số chính + đặc biệt",
            message=(
                f"Kỳ #{entry.get('target_draw_id')} ({actual.get('draw_date')}):\n"
                f"Kết quả thật: {actual_main} + đặc biệt {actual_special}\n"
                f"Bộ số đã dự đoán khớp HOÀN TOÀN (5/5 + ĐB):\n"
                + "\n".join(lines) +
                "\n\nLưu ý trung thực: đây là trùng khớp may mắn, KHÔNG phải bằng "
                "chứng model có khả năng dự đoán — xác suất mỗi bộ số vẫn là "
                "1/324.632. Hãy kiểm tra lại vé thật và chơi có trách nhiệm."
            ),
            priority="max",
            tags="trophy,tada,moneybag",
        )


def load_draws():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return parse_draws(rows)


def already_predicted(target_id: str) -> bool:
    """True if we've already logged a prediction for this target draw.
    The workflow now fires a primary + backup cron trigger per slot (to
    survive GitHub's scheduler occasionally dropping/delaying a run), so
    this guard is what stops the backup run from sending a duplicate
    notification when the primary run already succeeded."""
    for entry in load_log():
        if entry.get("target_draw_id") == target_id:
            return True
    return False


def main():
    draws = load_draws()
    if len(draws) < 90:
        print("Not enough historical draws yet to run the full pipeline.")
        return

    target_id_preview = _next_draw_id(draws[-1].draw_id)
    if already_predicted(target_id_preview):
        print(f"Draw #{target_id_preview} was already predicted in an earlier "
              f"run today (primary/backup dedup) -- skipping to avoid duplicate "
              f"notifications. Still resolving any newly-available past results.")
        notify_perfect_wins(resolve_all())
        return

    # --- Step 2: scheduled auto-tuning (no-op for uniform_seeded, kept for
    # transparency/consistency with the tuning_report.json history) ---
    print("=== Tuning ===")
    tuning.main()

    # --- Step 3: honest backtest -- confirms uniform_seeded performs the
    # same as a plain random baseline, as it must by construction ---
    print("\n=== Backtest ===")
    backtest_all.main()

    # --- Step 4: generate the 3 reproducible tickets ---
    tuned_params = load_tuned_params()
    pred = ensemble_predict(draws, tuned_params)

    last_draw = draws[-1]
    target_id = _next_draw_id(last_draw.draw_id)

    # --- Step 4b: reference & fair-comparison predictions ---
    print("\n=== Reference / comparison predictions ===")
    references = compute_references(target_id)

    def _ref_str(key):
        r = references.get(key, {})
        if not r.get("main"):
            return "n/a"
        return "-".join(f"{n:02d}" for n in r["main"]) + f" + {r['special']:02d}"

    print(f"Mốc công bằng (random): {_ref_str('random_fair')}")
    print(f"Ngẫu nhiên có lặp:      {_ref_str('random_repeat')}")
    print(f"Giống nhanaz-data:      {_ref_str('nhanaz')} "
          f"(available={references.get('nhanaz', {}).get('available')})")

    # --- Step 5: jackpot checks ---
    # threshold_crossed_date (set on a prior run when the jackpot first passed
    # 12B) lets check_jackpot pin the sharing round to "21:00 of the next day".
    jackpot = check_jackpot(last_draw.draw_date, last_draw.draw_time,
                            get_threshold_crossed_date())
    # Surface the "silent blind spot": if every jackpot source failed we
    # can't tell whether the next draw is the sharing round -- alert once.
    scrape_alert = check_scrape_alert(jackpot["jackpot_vnd"])
    early_alert = check_early_alert(jackpot["jackpot_vnd"], last_draw.draw_date)

    # NOTE: the old "high ensemble confidence" notify trigger is gone.
    # uniform_seeded assigns uniformly random scores by design -- there is
    # no such thing as an "unusually confident" round for a fair coin flip,
    # so that trigger would have just been noise dressed up as a signal.
    # Notifications now fire only for genuine jackpot-timing events.
    jackpot_round = jackpot["is_sharing_round"]
    should_notify = jackpot_round

    main_str = "-".join(f"{n:02d}" for n in pred["main_numbers"])
    special_str = f"{pred['special_number']:02d}"

    print(f"\n=== 3 bộ vé (chọn ngẫu nhiên có thể tái tạo) cho draw #{target_id} ===")
    for i, t in enumerate(pred["tickets"], 1):
        t_main = "-".join(f"{n:02d}" for n in t["main"])
        print(f"Vé #{i}: {t_main} + special {t['special']:02d}  (trace: {t['seed_trace_main']})")
    print(f"Jackpot: {jackpot}")
    print(f"Early alert: {early_alert}")
    print(f"Notify: {should_notify} (jackpot_round={jackpot_round})")
    print(f"Scrape alert: {scrape_alert}")

    # --- Step 7 (blind-spot): jackpot scrape failed on every source ---
    # Without a jackpot figure, is_sharing_round is forced False and both
    # jackpot alerts stay silent. Warn once so the user can check manually
    # instead of silently missing the sharing round.
    if scrape_alert["should_alert"]:
        ntfy_send(
            NTFY_TOPIC,
            title="⚠️ Lotto 5/35 – Không lấy được số Jackpot",
            message=(
                "Tất cả các nguồn tra cứu giá trị Giải Độc Đắc đều lỗi ở kỳ này, "
                "nên hệ thống TẠM THỜI không thể tự xác định kỳ CHIA GIẢI ĐỘC ĐẮC.\n"
                "Bạn nên kiểm tra thủ công trên vietlott.vn để không bỏ lỡ kỳ chia "
                "giải. Bạn sẽ chỉ nhận cảnh báo này 1 lần cho tới khi việc tra cứu "
                "hoạt động trở lại."
            ),
            priority="high",
            tags="warning",
        )

    # --- Step 7a: early jackpot-crossing alert (independent of main notify) ---
    if early_alert["should_alert"]:
        jackpot_str = f"{early_alert['jackpot_vnd']:,}".replace(",", ".")
        ntfy_send(
            NTFY_TOPIC,
            title="🔔 Lotto 5/35 – Jackpot vừa vượt 12 tỷ!",
            message=(
                f"Giải Độc Đắc hiện tại: {jackpot_str} đồng.\n"
                f"Nếu không ai trúng ở các kỳ tiếp theo, kỳ quay 21h00 của "
                f"ngày kế tiếp sẽ là kỳ CHIA GIẢI ĐỘC ĐẮC."
            ),
            priority="high",
            tags="rotating_light,moneybag",
        )

    # --- Step 7b: main notify ---
    if should_notify:
        reason_text = f"kỳ tới ({jackpot['next_draw_date']} 21:00) là kỳ CHIA GIẢI ĐỘC ĐẮC"

        ev_note = (
            "\n💡 Góc nhìn 'săn jackpot' thật: kỳ chia giải là lúc quỹ Độc Đắc "
            "được phân bổ xuống các giải thấp hơn NGAY CẢ KHI không ai khớp đủ "
            "5/5 — đây là điều thật duy nhất làm giá trị kỳ vọng của kỳ này cao "
            "hơn bình thường, không liên quan đến việc chọn số nào."
        )

        tickets_str = "\n".join(
            f"Vé #{i}: {'-'.join(f'{n:02d}' for n in t['main'])} + đặc biệt {t['special']:02d}"
            for i, t in enumerate(pred["tickets"], 1)
        )

        message = (
            f"Sau kỳ #{last_draw.draw_id} ({last_draw.draw_date}):\n"
            f"3 bộ vé (chọn ngẫu nhiên có thể tái tạo lại đúng từ mã seed):\n"
            f"{tickets_str}\n"
            f"— Để so sánh —\n"
            f"Mốc công bằng (ngẫu nhiên): {_ref_str('random_fair')}\n"
            f"Ngẫu nhiên có lặp lại: {_ref_str('random_repeat')}\n"
            f"Giống nhanaz-data: {_ref_str('nhanaz')}\n"
            f"{ev_note}\n"
            f"Lý do gửi: {reason_text}.\n"
            f"Lưu ý: đây LÀ ngẫu nhiên, không phải dự đoán có edge — mọi bộ số "
            f"đều có xác suất trúng như nhau. Mã seed từng vé cho phép bất kỳ ai "
            f"tự tái tạo lại đúng bộ số này. Chơi có trách nhiệm."
        )
        ntfy_send(
            NTFY_TOPIC,
            title="🎯 Lotto 5/35 – 3 bộ vé kỳ tới",
            message=message,
            priority="high" if jackpot_round else "default",
            tags="game_die,bar_chart",
        )

    # --- Step 8: log the full prediction ---
    per_strategy_serializable = {
        name: {"main": pick["main"], "special": pick["special"]}
        for name, pick in pred["per_strategy_picks"].items()
    }
    append_prediction({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "based_on_draw_id": last_draw.draw_id,
        "based_on_draw_date": last_draw.draw_date,
        "target_draw_id": target_id,
        "ensemble": {
            "main": pred["main_numbers"],
            "special": pred["special_number"],
            "confidence": round(pred["confidence"], 4),
        },
        "references": references,
        "per_strategy": per_strategy_serializable,
        "notified": should_notify,
        "jackpot_vnd": jackpot["jackpot_vnd"],
        "resolved": False,
        "actual": None,
        "hits": None,
    })

    # --- Step 9: resolve past predictions (+ alert on any 5-main+special win) ---
    print("\n=== Resolving past predictions ===")
    notify_perfect_wins(resolve_all())


if __name__ == "__main__":
    main()
