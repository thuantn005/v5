"""
run_pipeline.py
-----------------
Full automated pipeline, run twice daily by GitHub Actions:

  1. (data/all.csv already refreshed by fetch_data.py, a separate step)
  2. Ask Claude for the next draw's number pick (claude_predict.py).
  3. Check jackpot-sharing-round status + early "săn kỳ chia giải" alert.
  4. If this is the jackpot-sharing round, ask Claude for several diverse
     ticket sets that avoid a public reference tool's recommendations
     (jackpot_hunter.py) -- multiple tickets to buy for that round.
  5. Notify via ntfy: early jackpot-crossing alert (independent) + main
     prediction alert (every valid run) + hunter ticket sets when relevant.
  6. Log the prediction to state/ensemble_log.jsonl.
  7. Resolve any previously-logged predictions whose target draw has now
     happened (multi_log.resolve_all()).
  8. Generate dashboard data (generate_dashboard_data.py) for GitHub Pages.
"""

import csv
import os
from datetime import datetime, timezone

from model import parse_draws
from claude_predict import claude_pick
from jackpot_check import check_jackpot
from jackpot_watch import check_early_alert
from jackpot_hunter import hunter_predict
from notify_ntfy import send as ntfy_send
from multi_log import append_prediction, resolve_all, load_log, _next_draw_id

DATA_PATH = "data/all.csv"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "lotto535-thuan")


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
        resolve_all()
        return

    last_draw = draws[-1]
    target_id = target_id_preview

    # --- Step: jackpot checks (unchanged, independent of the prediction model) ---
    jackpot = check_jackpot(last_draw.draw_date, last_draw.draw_time)
    early_alert = check_early_alert(jackpot["jackpot_vnd"])
    jackpot_round = jackpot["is_sharing_round"]

    # --- Step: Claude prediction for the next draw ---
    print("\n=== Claude prediction ===")
    claude_sets = claude_pick(draws, n_sets=1)
    claude_pred = claude_sets[0] if claude_sets else None
    if claude_pred:
        main_str = "-".join(f"{n:02d}" for n in claude_pred["main"])
        special_str = f"{claude_pred['special']:02d}"
        print(f"Claude: {main_str} + special {special_str} -- {claude_pred['rationale']}")
    else:
        print("Claude prediction unavailable this run (API error or missing ANTHROPIC_API_KEY).")

    # --- Step: Jackpot Hunter multi-ticket pick, only for the sharing round ---
    hunter = None
    if jackpot_round:
        print("\n=== Jackpot Hunter multi-ticket pick ===")
        hunter = hunter_predict(draws)
        for i, s in enumerate(hunter["sets"], 1):
            main_str = "-".join(f"{n:02d}" for n in s["main"])
            print(f"  Vé {i}: {main_str} + special {s['special']:02d} -- {s['rationale']}")
        print(f"(reference_available={hunter['reference_available']})")

    should_notify = claude_pred is not None or jackpot_round

    print(f"\n=== Prediction for draw #{target_id} ===")
    print(f"Jackpot: {jackpot}")
    print(f"Early alert: {early_alert}")
    print(f"Notify: {should_notify}")

    # --- Early jackpot-crossing alert (independent of main notify) ---
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

    # --- Main prediction notify ---
    if should_notify:
        message_parts = [f"Sau kỳ #{last_draw.draw_id} ({last_draw.draw_date}):"]

        if claude_pred:
            main_str = "-".join(f"{n:02d}" for n in claude_pred["main"])
            special_str = f"{claude_pred['special']:02d}"
            message_parts.append(f"Bộ số Claude: {main_str} + đặc biệt {special_str}")
            message_parts.append(f"Lý do (Claude tự nêu): {claude_pred['rationale']}")
        else:
            message_parts.append("Claude không tạo được dự đoán ở lượt này (lỗi API).")

        if jackpot_round:
            message_parts.append(
                f"\n🎯 Kỳ tới ({jackpot['next_draw_date']} 21:00) là kỳ CHIA GIẢI ĐỘC ĐẮC."
            )
            message_parts.append(
                "💡 Góc nhìn 'săn jackpot' thật: kỳ chia giải là lúc quỹ Độc Đắc "
                "được phân bổ xuống các giải thấp hơn NGAY CẢ KHI không ai khớp đủ "
                "5/5 -- đây là điều thật duy nhất làm giá trị kỳ vọng của kỳ này cao "
                "hơn bình thường, không liên quan đến việc chọn số nào."
            )
            if hunter and hunter["sets"]:
                message_parts.append(
                    f"\n🎟️ {len(hunter['sets'])} bộ số gợi ý để mua nhiều vé "
                    f"(đã né {len(hunter['excluded_main'])} số công cụ tham khảo công khai "
                    f"gợi ý -- giảm rủi ro chia giải nếu trúng, không tăng xác suất trúng):"
                )
                for i, s in enumerate(hunter["sets"], 1):
                    main_str = "-".join(f"{n:02d}" for n in s["main"])
                    message_parts.append(f"  Vé {i}: {main_str} + đặc biệt {s['special']:02d}")
            elif hunter:
                message_parts.append("\n(Không tạo được bộ số Hunter ở lượt này -- lỗi API Claude.)")

        message_parts.append(
            "\nLưu ý: KHÔNG có model/AI nào làm tăng xác suất trúng thật (cố định "
            "1/324.632). Xem dashboard để biết chi tiết. Chơi có trách nhiệm."
        )

        ntfy_send(
            NTFY_TOPIC,
            title="🎯 Lotto 5/35 – Dự đoán Claude kỳ tới",
            message="\n".join(message_parts),
            priority="high" if jackpot_round else "default",
            tags="game_die,bar_chart",
        )

    # --- Log the prediction ---
    append_prediction({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "based_on_draw_id": last_draw.draw_id,
        "based_on_draw_date": last_draw.draw_date,
        "target_draw_id": target_id,
        "claude": claude_pred,
        "hunter_sets": hunter["sets"] if hunter else [],
        "notified": should_notify,
        "jackpot_vnd": jackpot["jackpot_vnd"],
        "resolved": False,
        "actual": None,
        "hits": None,
    })

    # --- Resolve past predictions ---
    print("\n=== Resolving past predictions ===")
    resolve_all()


if __name__ == "__main__":
    main()
