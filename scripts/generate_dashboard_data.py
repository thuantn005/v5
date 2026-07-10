"""
generate_dashboard_data.py
----------------------------
Aggregates state/ensemble_log.jsonl into docs/data.json for the GitHub Pages
dashboard. The project is now "3 vé mỗi kỳ": we track the cumulative hit-rate
of the three tickets (random_fair, random_repeat, nhanaz) against real results,
with the fair random ticket as the honest yardstick.
"""

import json
import os
import statistics
from datetime import datetime, timezone

from multi_log import load_log

OUTPUT_PATH = "docs/data.json"

TICKET_KEYS = ["ticket_1", "ticket_2", "ticket_3", "ticket_momentum",
               "ticket_momentum_top", "ticket_vedic_chakra", "ticket_virahanka",
               "random_fair"]
TICKET_LABELS = {
    "random_fair": "Mốc so sánh công bằng",
    "ticket_1": "Ngẫu nhiên #1",
    "ticket_2": "Ngẫu nhiên #2",
    "ticket_3": "Ngẫu nhiên #3",
    "ticket_momentum": "Quán tính (momentum)",
    "ticket_momentum_top": "Quán tính xuất sắc nhất",
    "ticket_vedic_chakra": "Vòng số Vedic (Chakra)",
    "ticket_virahanka": "Dãy Virahanka (Fibonacci Ấn Độ)",
}


def build_performance_over_time(resolved_entries):
    """Cumulative average main-hits per ticket, chronological."""
    running_sums = {k: 0.0 for k in TICKET_KEYS}
    running_counts = {k: 0 for k in TICKET_KEYS}
    series = {k: [] for k in TICKET_KEYS}
    labels = []
    for e in resolved_entries:
        hits = e.get("hits") or {}
        if not any(k in hits for k in TICKET_KEYS):
            continue  # skip legacy (pre-ticket) rows
        labels.append(e["target_draw_id"])
        for k in TICKET_KEYS:
            h = hits.get(k)
            if h is not None:
                running_sums[k] += h["main_hits"]
                running_counts[k] += 1
            avg = (running_sums[k] / running_counts[k]) if running_counts[k] else None
            series[k].append(round(avg, 4) if avg is not None else None)
    return {"labels": labels, "series": series, "labels_by_key": TICKET_LABELS}


def build_ticket_accuracy(resolved_entries):
    summary = {}
    for k in TICKET_KEYS:
        hits_list = [e["hits"][k]["main_hits"] for e in resolved_entries
                     if (e.get("hits") or {}).get(k)]
        special_list = [e["hits"][k]["special_hit"] for e in resolved_entries
                        if (e.get("hits") or {}).get(k)]
        if not hits_list:
            continue
        summary[k] = {
            "label": TICKET_LABELS[k],
            "n": len(hits_list),
            "avg_main_hits": round(statistics.mean(hits_list), 4),
            "special_hit_rate": round(statistics.mean(special_list), 4),
            "expected_random_main_hits": 0.7143,  # 5*5/35
        }
    return summary


def build_draw_history(resolved_entries, limit=50):
    rows = []
    for e in reversed(resolved_entries[-limit:]):
        hits = e.get("hits", {}) or {}

        def entry(label, main, special, hits_key):
            h = hits.get(hits_key) or {}
            return {
                "label": label, "main": main, "special": special,
                "main_hits": h.get("main_hits"),
                "special_hit": bool(h.get("special_hit")) if h else None,
            }

        predictions = []
        tickets = e.get("tickets")
        if tickets:
            for k in TICKET_KEYS:
                t = tickets.get(k)
                if t and t.get("main"):
                    predictions.append(entry(t.get("label") or TICKET_LABELS[k], t["main"], t["special"], k))
        else:
            # legacy rows: show whatever they had (ensemble/references/per_strategy/hunter)
            if e.get("ensemble"):
                predictions.append(entry("Ensemble", e["ensemble"]["main"], e["ensemble"]["special"], "ensemble"))
            for k in ("random_fair", "random_repeat", "nhanaz"):
                r = (e.get("references") or {}).get(k)
                if r and r.get("main"):
                    predictions.append(entry(r.get("label") or k, r["main"], r["special"], f"ref_{k}"))
            for k, pick in (e.get("per_strategy") or {}).items():
                if pick and pick.get("main") and pick.get("special") is not None:
                    predictions.append(entry(TICKET_LABELS.get(k, k), pick["main"], pick["special"], k))
            h = e.get("hunter")
            if h and h.get("main"):
                predictions.append(entry("Jackpot Hunter", h["main"], h["special"], "jackpot_hunter"))

        rows.append({
            "target_draw_id": e["target_draw_id"],
            "draw_date": e["actual"]["draw_date"],
            "actual_main": e["actual"]["main"],
            "actual_special": e["actual"]["special"],
            "predictions": predictions,
        })
    return rows


def _normalize_latest(entry: dict) -> dict:
    """Ensure latest_prediction always exposes a `tickets` key the dashboard JS
    expects, regardless of whether the log entry uses the new `tickets` format
    or the older `per_strategy` + `references` format."""
    if not entry or entry.get("tickets"):
        return entry
    tickets = {}
    for k, pick in (entry.get("per_strategy") or {}).items():
        if pick and pick.get("main") and pick.get("special") is not None:
            tickets[k] = {
                "main": pick["main"],
                "special": pick["special"],
                "label": pick.get("label") or TICKET_LABELS.get(k, k),
                "trace": pick.get("trace"),
            }
    for k, ref in (entry.get("references") or {}).items():
        if ref and ref.get("main") and ref.get("special") is not None:
            tickets[k] = {
                "main": ref["main"],
                "special": ref["special"],
                "label": ref.get("label") or TICKET_LABELS.get(k, k),
                "trace": ref.get("trace"),
                "method": ref.get("method"),
            }
    ens = entry.get("ensemble")
    if ens and ens.get("main") and ens.get("special") is not None:
        tickets["ensemble"] = {
            "main": ens["main"],
            "special": ens["special"],
            "label": TICKET_LABELS.get("ensemble", "Ensemble"),
        }
    return {**entry, "tickets": tickets}


def main():
    log_entries = load_log()
    resolved = [e for e in log_entries if e.get("resolved")]

    latest = None
    unresolved = [e for e in log_entries if not e.get("resolved")]
    if unresolved:
        latest = _normalize_latest(unresolved[-1])
    elif log_entries:
        latest = _normalize_latest(log_entries[-1])

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_prediction": latest,
        "ticket_keys": TICKET_KEYS,
        "performance_over_time": build_performance_over_time(resolved),
        "ticket_accuracy": build_ticket_accuracy(resolved),
        "draw_history": build_draw_history(resolved),
        "n_resolved_predictions": len([e for e in resolved if e.get("tickets")]),
    }

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Wrote {OUTPUT_PATH} ({data['n_resolved_predictions']} resolved ticket-draws, "
          f"{len(log_entries)} total log rows)")


if __name__ == "__main__":
    main()
