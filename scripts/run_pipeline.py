"""
run_pipeline.py
-----------------
Automated pipeline, run twice daily by GitHub Actions. Each draw it publishes
4 tickets (an Ensemble kept separately + 3 comparison tickets):

  1. (data/all.csv already refreshed by fetch_data.py, a separate step)
  2. Build the tickets for the next draw:
       - ensemble      : vote of gap_zscore + momentum + crowd_avoidance
       - random_fair   : fair random baseline (reproducible via trace code)
       - random_repeat : random with replacement
       - nhanaz        : mirror of the public nhanaz-data prediction
  3. Check jackpot-sharing-round status + early / blind-spot alerts.
  4. Send the "3 vé" ntfy notification (high priority on a sharing round).
  5. Log the 3 tickets to state/ensemble_log.jsonl.
  6. Resolve any previously-logged tickets whose draw has now happened, and
     alert on any 5-main + special perfect match.
  7. (generate_dashboard_data.py runs as a separate workflow step.)
"""

import csv
import os
import sys
from datetime import datetime, timezone

from model import parse_draws
from jackpot_check import check_jackpot
from jackpot_watch import check_early_alert, check_scrape_alert
from references import compute_tickets
from ensemble import ensemble_predict
from notify_ntfy import send as _ntfy_send_raw
from multi_log import append_prediction, resolve_all, load_log, _next_draw_id

DATA_PATH = "data/all.csv"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "lotto535-thuan")

# Tickets shown to the user, in display order. "ensemble" is kept as a
# separate 4th ticket (the multi-model voting pick); the other three are the
# random baselines + nhanaz mirror. None of them beat random -- the fair
# ticket is the yardstick that makes that plain.
TICKET_ORDER = ["ensemble", "random_fair", "random_repeat", "nhanaz"]


def ntfy_send(*args, **kwargs):
    """Send an ntfy notification, but NEVER let a notification failure abort
    the pipeline. A transient ntfy.sh outage / rate-limit / network blip must
    not stop us from logging the tickets and resolving past results."""
    try:
        _ntfy_send_raw(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 -- notifications are best-effort
        print(f"WARNING: ntfy notification failed (continuing): {e}", file=sys.stderr)


def _ticket_str(ticket: dict) -> str:
    if not ticket or not ticket.get("main"):
        return "n/a"
    return "-".join(f"{n:02d}" for n in ticket["main"]) + f" + {ticket['special']:02d}"


def notify_perfect_wins(newly_resolved):
    """When any logged ticket for a just-resolved draw matched all 5 main
    numbers AND the special number, fire a celebratory ntfy. Runs off the
    entries resolve_all() reports as newly resolved, so each win alerts
    exactly once."""
    for entry in newly_resolved:
        actual = entry.get("actual") or {}
        hits = entry.get("hits") or {}
        tickets = entry.get("tickets") or {}
        winners = [
            key for key, h in hits.items()
            if h and h.get("main_hits") == 5 and h.get("special_hit")
        ]
        if not winners:
            continue

        actual_main = "-".join(f"{n:02d}" for n in actual.get("main", []))
        actual_special = f"{actual.get('special'):02d}" if actual.get("special") is not None else "??"
        lines = []
        for key in winners:
            t = tickets.get(key, {})
            lines.append(f"• {t.get('label', key)}: {_ticket_str(t)}")

        ntfy_send(
            NTFY_TOPIC,
            title="🏆 TRÚNG! Vé khớp 5 số chính + đặc biệt",
            message=(
                f"Kỳ #{entry.get('target_draw_id')} ({actual.get('draw_date')}):\n"
                f"Kết quả thật: {actual_main} + đặc biệt {actual_special}\n"
                f"Vé đã khớp HOÀN TOÀN (5/5 + ĐB):\n"
                + "\n".join(lines) +
                "\n\nLưu ý trung thực: đây là trùng khớp may mắn, KHÔNG phải bằng "
                "chứng có khả năng dự đoán — xác suất mỗi bộ số vẫn là 1/324.632. "
                "Hãy kiểm tra lại vé thật và chơi có trách nhiệm."
            ),
            priority="max",
            tags="trophy,tada,moneybag",
        )


def load_draws():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return parse_draws(rows)


def already_predicted(target_id: str) -> bool:
    """True if we've already logged tickets for this target draw. The workflow
    fires a primary + backup cron trigger per slot (to survive GitHub's
    scheduler occasionally dropping/delaying a run), so this guard stops the
    backup run from sending a duplicate notification."""
    for entry in load_log():
        if entry.get("target_draw_id") == target_id:
            return True
    return False


def main():
    draws = load_draws()
    if len(draws) < 90:
        print("Not enough historical draws yet to run the pipeline.")
        return

    last_draw = draws[-1]
    target_id = _next_draw_id(last_draw.draw_id)

    if already_predicted(target_id):
        print(f"Draw #{target_id} was already predicted in an earlier run today "
              f"(primary/backup dedup) -- skipping to avoid duplicate notifications. "
              f"Still resolving any newly-available past results.")
        notify_perfect_wins(resolve_all())
        return

    # --- Step 2: build the tickets (Ensemble + 3 references) ---
    print(f"=== Tickets for draw #{target_id} ===")
    tickets = compute_tickets(target_id)
    ens = ensemble_predict(draws)
    tickets["ensemble"] = {
        "label": "Ensemble (gộp 3 model: gap_zscore + momentum + crowd_avoidance)",
        "main": ens["main_numbers"],
        "special": ens["special_number"],
        "confidence": round(ens["confidence"], 4),
    }
    for key in TICKET_ORDER:
        t = tickets.get(key, {})
        print(f"{t.get('label', key)}: {_ticket_str(t)}"
              + (f"  [{t['trace']}]" if t.get("trace") else "")
              + ("" if t.get("main") else "  (không lấy được)"))

    # --- Step 3: jackpot checks ---
    jackpot = check_jackpot(last_draw.draw_date, last_draw.draw_time)
    scrape_alert = check_scrape_alert(jackpot["jackpot_vnd"])
    early_alert = check_early_alert(jackpot["jackpot_vnd"])
    jackpot_round = jackpot["is_sharing_round"]
    print(f"Jackpot: {jackpot}")
    print(f"Scrape alert: {scrape_alert} | Early alert: {early_alert}")

    # --- Step 3a (blind-spot): every jackpot source failed ---
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

    # --- Step 3b: early jackpot-crossing alert ---
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

    # --- Step 4: the "3 vé" notification (every draw) ---
    ticket_lines = []
    for key in TICKET_ORDER:
        t = tickets.get(key, {})
        line = f"• {t.get('label', key)}: {_ticket_str(t)}"
        if t.get("trace"):
            line += f"  [{t['trace']}]"
        ticket_lines.append(line)

    ev_note = ""
    if jackpot_round:
        ev_note = (
            f"\n💡 Kỳ tới ({jackpot['next_draw_date']} 21:00) là kỳ CHIA GIẢI ĐỘC "
            "ĐẮC: quỹ Độc Đắc được phân bổ xuống các giải thấp hơn ngay cả khi "
            "không ai khớp đủ 5/5 — điều thật duy nhất làm kỳ vọng kỳ này cao hơn, "
            "không liên quan tới việc chọn số nào."
        )

    message = (
        f"4 vé cho kỳ #{target_id} (dựa trên dữ liệu tới hết kỳ #{last_draw.draw_id} "
        f"ngày {last_draw.draw_date}):\n"
        + "\n".join(ticket_lines)
        + ev_note +
        "\n\nLưu ý trung thực: KHÔNG bộ số nào tăng xác suất trúng — 'mốc so sánh "
        "công bằng' là chuẩn để thấy rõ điều đó. Xác suất Jackpot cố định "
        "1/324.632. Chơi có trách nhiệm."
    )
    ntfy_send(
        NTFY_TOPIC,
        title="🎲 Lotto 5/35 – 4 vé kỳ tới",
        message=message,
        priority="high" if jackpot_round else "default",
        tags="game_die,ticket",
    )

    # --- Step 5: log the 3 tickets ---
    append_prediction({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "based_on_draw_id": last_draw.draw_id,
        "based_on_draw_date": last_draw.draw_date,
        "target_draw_id": target_id,
        "tickets": tickets,
        "jackpot_vnd": jackpot["jackpot_vnd"],
        "resolved": False,
        "actual": None,
        "hits": None,
    })

    # --- Step 6: resolve past tickets (+ alert on any 5-main+special win) ---
    print("\n=== Resolving past tickets ===")
    notify_perfect_wins(resolve_all())


if __name__ == "__main__":
    main()
