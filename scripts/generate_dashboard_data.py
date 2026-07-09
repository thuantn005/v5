"""
generate_dashboard_data.py
----------------------------
Aggregates state/ensemble_log.jsonl into a single docs/data.json consumed
by docs/index.html (the GitHub Pages dashboard). This is Claude's REAL
track record (predictions actually made and later resolved against real
draws) -- not a retroactive backtest, since re-running an LLM over
hundreds of historical draws isn't cheap/practical the way the old
deterministic strategies were.
"""

import json
import os
import statistics

from multi_log import load_log

OUTPUT_PATH = "docs/data.json"


def build_performance_over_time(resolved_entries):
    """Running (cumulative) average main-hits for Claude's real predictions,
    in chronological order, for the '📈 Biểu đồ hiệu năng theo thời gian' chart."""
    labels = []
    series = []
    running_sum, running_count = 0.0, 0

    for e in resolved_entries:
        hits = e["hits"].get("claude")
        if hits is None:
            continue
        labels.append(e["target_draw_id"])
        running_sum += hits["main_hits"]
        running_count += 1
        series.append(round(running_sum / running_count, 4))

    return {"labels": labels, "series": {"claude": series}}


def build_model_accuracy(resolved_entries):
    hits_list = [e["hits"]["claude"]["main_hits"] for e in resolved_entries if e["hits"].get("claude")]
    special_list = [e["hits"]["claude"]["special_hit"] for e in resolved_entries if e["hits"].get("claude")]
    if not hits_list:
        return {}
    return {
        "claude": {
            "n": len(hits_list),
            "avg_main_hits": round(statistics.mean(hits_list), 4),
            "special_hit_rate": round(statistics.mean(special_list), 4),
        }
    }


def build_draw_history(resolved_entries, limit=50):
    rows = []
    for e in reversed(resolved_entries[-limit:]):
        claude = e.get("claude")
        claude_hits = e["hits"].get("claude")
        rows.append({
            "target_draw_id": e["target_draw_id"],
            "draw_date": e["actual"]["draw_date"],
            "actual_main": e["actual"]["main"],
            "actual_special": e["actual"]["special"],
            "claude_predicted_main": claude["main"] if claude else None,
            "claude_predicted_special": claude["special"] if claude else None,
            "claude_main_hits": claude_hits["main_hits"] if claude_hits else None,
            "claude_special_hit": bool(claude_hits["special_hit"]) if claude_hits else None,
        })
    return rows


def main():
    log_entries = load_log()
    resolved = [e for e in log_entries if e.get("resolved")]

    latest_prediction = None
    unresolved = [e for e in log_entries if not e.get("resolved")]
    if unresolved:
        latest_prediction = unresolved[-1]
    elif log_entries:
        latest_prediction = log_entries[-1]

    data = {
        "generated_at": None,
        "latest_prediction": latest_prediction,
        "performance_over_time": build_performance_over_time(resolved),
        "model_accuracy": build_model_accuracy(resolved),
        "draw_history": build_draw_history(resolved),
        "n_resolved_predictions": len(resolved),
    }

    from datetime import datetime, timezone
    data["generated_at"] = datetime.now(timezone.utc).isoformat()

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Wrote {OUTPUT_PATH} ({len(resolved)} resolved predictions, "
          f"{len(log_entries)} total)")


if __name__ == "__main__":
    main()
