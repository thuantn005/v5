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
from jackpot_watch import check_share_draw, get_threshold_crossed_date
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


def notify_resolved_comparison(newly_resolved):
    """Push a "đối chiếu kết quả" summary for every draw that just became
    resolvable — ensemble + each strategy vs. the real numbers, with hit
    counts. Driven by resolve_all()'s newly_resolved list, so if a slot was
    skipped (e.g. cron-job.org dropped a run), the đối chiếu for that kỳ is
    sent automatically the next time the pipeline runs, exactly once per
    draw (the `resolved` flag prevents re-notifying)."""
    for entry in newly_resolved:
        actual = entry.get("actual") or {}
        hits = entry.get("hits") or {}
        if not actual or not hits:
            continue

        actual_main = "-".join(f"{n:02d}" for n in actual.get("main", []))
        asp = actual.get("special")
        actual_special = f"{asp:02d}" if asp is not None else "??"

        # Report the ensemble first, then each individual strategy (which
        # already includes the fair random baseline). Skip the duplicated
        # ref_* / legacy keys so the message stays clean.
        report_keys = (["ensemble"] if "ensemble" in hits else []) + [
            k for k in (entry.get("per_strategy") or {}) if k in hits
        ]

        def _label(key):
            if key == "ensemble":
                return "🧠 Ensemble"
            return (entry.get("per_strategy") or {}).get(key, {}).get("label", key)

        lines = []
        best = 0
        for key in report_keys:
            h = hits.get(key) or {}
            main_hits = int(h.get("main_hits", 0))
            special_hit = bool(h.get("special_hit"))
            best = max(best, main_hits + (1 if special_hit else 0))
            main, special = _predicted_numbers(entry, key)
            main_str = "-".join(f"{n:02d}" for n in (main or []))
            sp_str = f"{special:02d}" if special is not None else "??"
            mark = " 🎯ĐB" if special_hit else ""
            lines.append(f"• {_label(key)}: {main_str} + {sp_str} → {main_hits}/5{mark}")

        ntfy_send(
            NTFY_TOPIC,
            title=f"📊 Đối chiếu kỳ #{entry.get('target_draw_id')} ({actual.get('draw_date')})",
            message=(
                f"Kết quả thật: {actual_main} + đặc biệt {actual_special}\n\n"
                + "\n".join(lines)
                + f"\n\nCao nhất: {best} khớp. Mọi bộ số có xác suất như nhau — "
                "chơi có trách nhiệm."
            ),
            priority="default",
            tags="bar_chart",
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
              f"run today (primary/backup dedup) -- skipping prediction. "
              f"Still resolving results and checking jackpot state.")
        newly = resolve_all()
        notify_perfect_wins(newly)
        notify_resolved_comparison(newly)
        # Vẫn chạy jackpot state machine — reminder kỳ chia giải phải gửi
        # đúng ngày dù pipeline dedup bỏ qua bước predict.
        jackpot = check_jackpot(draws[-1].draw_date, draws[-1].draw_time,
                                get_threshold_crossed_date(),
                                last_draw_id=draws[-1].draw_id)
        for ev in check_share_draw(jackpot["jackpot_vnd"],
                                   last_draw_id=draws[-1].draw_id,
                                   last_draw_date=draws[-1].draw_date):
            ntfy_send(NTFY_TOPIC, title=ev["title"],
                      message=ev["message"], priority=ev["priority"],
                      tags=ev["tags"])
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

    # --- Step 5: jackpot check (scrape value) ---
    jackpot = check_jackpot(last_draw.draw_date, last_draw.draw_time,
                            get_threshold_crossed_date(),
                            last_draw_id=last_draw.draw_id)

    jackpot_vnd   = jackpot["jackpot_vnd"]
    jackpot_round = jackpot["is_sharing_round"]

    print(f"\n=== Bộ vé cho draw #{target_id} ===")
    t_main = "-".join(f"{n:02d}" for n in pred["main_numbers"])
    print(f"🧠 Neural: {t_main} + special {pred['special_number']:02d}")
    print(f"Jackpot: {jackpot_vnd} VND | sharing_round={jackpot_round}")
    print(f"Reason: {jackpot['reason']}")

    # --- Step 7: jackpot state machine ---
    # Handles: scheduled / reminder / cancelled / completed / scrape_fail
    share_events = check_share_draw(
        jackpot_vnd,
        last_draw_id=last_draw.draw_id,
        last_draw_date=last_draw.draw_date,
    )

    neural_str  = "-".join(f"{n:02d}" for n in pred["main_numbers"])
    neural_line = f"🧠 Neural: {neural_str} + đặc biệt {pred['special_number']:02d}"
    ev_note = (
        "\n💡 Kỳ chia giải: quỹ Độc Đắc phân bổ xuống giải thấp hơn ngay cả khi "
        "không ai trúng 5/5 — lý do duy nhất làm kỳ vọng cao hơn bình thường, "
        "không liên quan đến việc chọn số."
    )

    for ev in share_events:
        extra = ""
        if ev["kind"] in ("scheduled", "reminder"):
            extra = (
                f"\n{neural_line}"
                f"\n🎯 Ngẫu nhiên chuẩn: {_ref_str('random_fair')}"
                f"{ev_note}"
                f"\nMọi bộ số có xác suất trúng như nhau. Chơi có trách nhiệm."
            )
        ntfy_send(
            NTFY_TOPIC,
            title=ev["title"],
            message=ev["message"] + extra,
            priority=ev["priority"],
            tags=ev["tags"],
        )

    should_notify = bool(share_events)
    print(f"Notify: {should_notify} (events={[e['kind'] for e in share_events]})")


    # --- Step 8: log the full prediction ---
    per_strategy_serializable = {
        name: {
            "main":    pick["main"],
            "special": pick["special"],
            "label":   pick.get("label", name),
            "trace":   pick.get("trace"),
        }
        for name, pick in pred["per_strategy_picks"].items()
    }
    # Include random_fair in per_strategy so resolve_all() tracks its hits
    # alongside ticket_neural for honest dashboard comparison.
    rf = references.get("random_fair")
    if rf and rf.get("main"):
        per_strategy_serializable["random_fair"] = {
            "main": rf["main"], "special": rf["special"],
            "trace": rf.get("trace"),
            "label": rf.get("label", "Mốc so sánh công bằng"),
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

    # --- Step 9: resolve past predictions (+ alert on any 5-main+special win,
    # + đối chiếu summary for every kỳ that just resolved, incl. skipped slots) ---
    print("\n=== Resolving past predictions ===")
    newly = resolve_all()
    notify_perfect_wins(newly)
    notify_resolved_comparison(newly)


if __name__ == "__main__":
    main()
