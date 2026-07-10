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
from jackpot_watch import check_early_alert, check_scrape_alert
from jackpot_hunter import hunter_predict
from notify_ntfy import send as _ntfy_send_raw
from multi_log import append_prediction, resolve_all, load_log, _next_draw_id

import tuning
import backtest_all
import ensemble_calibrate

DATA_PATH = "data/all.csv"
CALIBRATION_PATH = "state/ensemble_calibration.json"
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


def load_draws():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return parse_draws(rows)


def load_calibration():
    if not os.path.exists(CALIBRATION_PATH):
        return None
    with open(CALIBRATION_PATH, encoding="utf-8") as f:
        return json.load(f)


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
        resolve_all()
        return

    # --- Step 2: scheduled auto-tuning ---
    print("=== Tuning ===")
    tuning.main()

    # --- Step 3: honest backtest of every strategy ---
    print("\n=== Backtest all strategies ===")
    backtest_all.main()

    # --- Step 4: calibrate ensemble notify threshold ---
    print("\n=== Calibrate ensemble ===")
    ensemble_calibrate.main()

    # --- Step 5: Ensemble Voting prediction ---
    tuned_params = load_tuned_params()
    pred = ensemble_predict(draws, tuned_params)
    calibration = load_calibration()
    threshold = calibration["notify_threshold_confidence"] if calibration else None

    # --- Step 5b: Jackpot Hunter pick (crowd-avoidance vs public reference tool) ---
    print("\n=== Jackpot Hunter pick ===")
    hunter = hunter_predict(draws, tuned_params)
    hunter_main_str = "-".join(f"{n:02d}" for n in hunter["main_numbers"])
    hunter_special_str = f"{hunter['special_number']:02d}"
    print(f"Hunter: {hunter_main_str} + special {hunter_special_str} "
          f"(reference_available={hunter['reference_available']})")

    last_draw = draws[-1]
    target_id = _next_draw_id(last_draw.draw_id)

    # --- Step 6: jackpot checks ---
    jackpot = check_jackpot(last_draw.draw_date, last_draw.draw_time)
    # Surface the "silent blind spot": if every jackpot source failed we
    # can't tell whether the next draw is the sharing round -- alert once.
    scrape_alert = check_scrape_alert(jackpot["jackpot_vnd"])
    early_alert = check_early_alert(jackpot["jackpot_vnd"])

    high_confidence = threshold is not None and pred["confidence"] >= threshold
    jackpot_round = jackpot["is_sharing_round"]
    should_notify = high_confidence or jackpot_round

    main_str = "-".join(f"{n:02d}" for n in pred["main_numbers"])
    special_str = f"{pred['special_number']:02d}"

    print(f"\n=== Ensemble prediction for draw #{target_id} ===")
    print(f"Main: {main_str} + special {special_str} "
          f"(confidence={pred['confidence']:.3f}, threshold={threshold})")
    print(f"Jackpot: {jackpot}")
    print(f"Early alert: {early_alert}")
    print(f"Notify: {should_notify} (high_confidence={high_confidence}, jackpot_round={jackpot_round})")
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

    # --- Step 7b: main ensemble notify ---
    if should_notify:
        reasons = []
        if high_confidence:
            reasons.append("độ tin cậy ensemble ở mức top ~5% lịch sử")
        if jackpot_round:
            reasons.append(f"kỳ tới ({jackpot['next_draw_date']} 21:00) là kỳ CHIA GIẢI ĐỘC ĐẮC")
        reason_text = " và ".join(reasons)

        ev_note = ""
        if jackpot_round:
            ev_note = (
                "\n💡 Góc nhìn 'săn jackpot' thật: kỳ chia giải là lúc quỹ Độc Đắc "
                "được phân bổ xuống các giải thấp hơn NGAY CẢ KHI không ai khớp đủ "
                "5/5 — đây là điều thật duy nhất làm giá trị kỳ vọng của kỳ này cao "
                "hơn bình thường, không liên quan đến việc chọn số nào."
                "\n➡️ Khuyến nghị cho kỳ chia giải: ưu tiên bộ JACKPOT HUNTER ở trên "
                "(né số đám đông hay chọn). Kỳ chia giải thu hút nhiều người chơi hơn, "
                "nên rủi ro phải CHIA giải nếu trúng cũng cao hơn — né đám đông là "
                "cách duy nhất có thật để tối đa số tiền thực nhận nếu trúng."
            )

        leaderboard = None
        try:
            with open("state/model_leaderboard.json", encoding="utf-8") as f:
                leaderboard = json.load(f)
        except FileNotFoundError:
            pass
        top_model = leaderboard["ranking_by_avg_hits"][0]["strategy"] if leaderboard else "n/a"

        message = (
            f"Sau kỳ #{last_draw.draw_id} ({last_draw.draw_date}):\n"
            f"Bộ số Ensemble ({len(pred['per_strategy_picks'])} model): {main_str} + đặc biệt {special_str}\n"
            f"Bộ số Jackpot Hunter (né số công cụ tham khảo công khai gợi ý, "
            f"giảm rủi ro chia giải nếu trúng): {hunter_main_str} + đặc biệt {hunter_special_str}\n"
            f"Model dẫn đầu backtest hiện tại: {top_model} (tham khảo, không phải bảo chứng)"
            f"{ev_note}\n"
            f"Lý do gửi: {reason_text}.\n"
            f"Lưu ý: KHÔNG có model nào làm tăng xác suất trúng thật. Xem "
            f"dashboard để biết chi tiết & so sánh với ngẫu nhiên. Chơi có "
            f"trách nhiệm."
        )
        ntfy_send(
            NTFY_TOPIC,
            title="🎯 Lotto 5/35 – Dự đoán Ensemble kỳ tới",
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
        "hunter": {
            "main": hunter["main_numbers"],
            "special": hunter["special_number"],
            "reference_available": hunter["reference_available"],
            "excluded_main": hunter.get("excluded_main", []),
            "excluded_special": hunter.get("excluded_special", []),
        },
        "per_strategy": per_strategy_serializable,
        "notified": should_notify,
        "jackpot_vnd": jackpot["jackpot_vnd"],
        "resolved": False,
        "actual": None,
        "hits": None,
    })

    # --- Step 9: resolve past predictions ---
    print("\n=== Resolving past predictions ===")
    resolve_all()


if __name__ == "__main__":
    main()
