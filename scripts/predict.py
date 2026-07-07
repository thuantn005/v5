"""
predict.py
-----------
Main entry point run by the GitHub Actions workflow.

Steps:
  1. Load latest historical data (data/all.csv, refreshed by fetch_data.py).
  2. Generate a prediction for the *next* draw + internal confidence score.
  3. Load calibration.json (from backtest_calibrate.py) to get the
     notify threshold.
  4. Check the jackpot-sharing-round condition (jackpot_check.py) -- per
     Vietlott's rule, this is ONLY the 21:00 draw of the day right after
     the jackpot is confirmed above 12 billion VND.
  5. If confidence >= threshold OR it's the jackpot-sharing round,
     send an ntfy notification -- otherwise stay silent.
  6. Always append the prediction to state/predictions_log.csv so accuracy
     can be tracked honestly over time (check_results.py resolves these
     against real outcomes on the next run, and the workflow commits the
     log back to the repo).

Every notification message explicitly states the heuristic nature of the
score, per the project's honesty-first design.
"""

import csv
import json
import os
from datetime import datetime, timezone

from model import parse_draws, predict_next, DEFAULT_WINDOW
from jackpot_check import check_jackpot
from notify_ntfy import send as ntfy_send
from check_results import FIELDNAMES

DATA_PATH = "data/all.csv"
CALIBRATION_PATH = "state/calibration.json"
LOG_PATH = "state/predictions_log.csv"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "lotto535-thuan")


def load_draws():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return parse_draws(rows)


def load_calibration():
    if not os.path.exists(CALIBRATION_PATH):
        return None
    with open(CALIBRATION_PATH, encoding="utf-8") as f:
        return json.load(f)


def next_draw_id(draw_id: str) -> str:
    width = len(draw_id)
    return str(int(draw_id) + 1).zfill(width)


def append_log(entry: dict):
    file_exists = os.path.exists(LOG_PATH)
    row = {field: entry.get(field, "") for field in FIELDNAMES}
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    draws = load_draws()
    if len(draws) < 30:
        print("Not enough historical draws yet to predict.")
        return

    last_draw = draws[-1]
    pred = predict_next(draws, window=DEFAULT_WINDOW)
    calibration = load_calibration()
    threshold = calibration["notify_threshold_confidence"] if calibration else None

    jackpot = check_jackpot(last_draw.draw_date, last_draw.draw_time)

    high_confidence = threshold is not None and pred["confidence"] >= threshold
    jackpot_round = jackpot["is_sharing_round"]

    should_notify = high_confidence or jackpot_round

    numbers_str = "-".join(f"{n:02d}" for n in pred["main_numbers"])
    special_str = f"{pred['special_number']:02d}"
    target_id = next_draw_id(last_draw.draw_id)

    print(f"Last draw: #{last_draw.draw_id} ({last_draw.draw_date} {last_draw.draw_time}) "
          f"{last_draw.numbers} + special {last_draw.special}")
    print(f"Prediction for draw #{target_id}: {numbers_str} + special {special_str} "
          f"(confidence={pred['confidence']:.3f}, threshold={threshold})")
    print(f"Jackpot check: {jackpot}")
    print(f"Notify decision: {should_notify} "
          f"(high_confidence={high_confidence}, jackpot_round={jackpot_round})")

    if should_notify:
        reasons = []
        if high_confidence:
            reasons.append("điểm số nội bộ của mô hình đang ở mức top ~5% lịch sử")
        if jackpot_round:
            reasons.append(
                f"kỳ tới ({jackpot['next_draw_date']} 21:00) là kỳ CHIA GIẢI ĐỘC ĐẮC "
                f"(jackpot đã vượt 12 tỷ)"
            )
        reason_text = " và ".join(reasons)

        title = "🎯 Lotto 5/35 – dự đoán kỳ tới"
        message = (
            f"Sau kỳ #{last_draw.draw_id} ({last_draw.draw_date}):\n"
            f"Số chính: {numbers_str}\n"
            f"Số đặc biệt: {special_str}\n"
            f"Lý do gửi: {reason_text}.\n"
            f"Lưu ý: đây là điểm số heuristic (tần suất + độ trễ), KHÔNG phải "
            f"xác suất trúng thật. Backtest cho thấy không có tương quan thật "
            f"với kết quả. Chơi có trách nhiệm."
        )
        ntfy_send(NTFY_TOPIC, title, message, priority="high" if jackpot_round else "default",
                   tags="game_die,moneybag")

    append_log({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "based_on_draw_id": last_draw.draw_id,
        "based_on_draw_date": last_draw.draw_date,
        "target_draw_id": target_id,
        "predicted_main_numbers": numbers_str,
        "predicted_special": special_str,
        "confidence": round(pred["confidence"], 4),
        "threshold": threshold,
        "jackpot_vnd": jackpot["jackpot_vnd"],
        "notified": should_notify,
    })


if __name__ == "__main__":
    main()
