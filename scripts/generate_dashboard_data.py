"""
generate_dashboard_data.py
----------------------------
Aggregates state/model_leaderboard.json, state/ensemble_calibration.json,
state/tuning_report.json, and state/ensemble_log.jsonl into a single
docs/data.json consumed by docs/index.html (the GitHub Pages dashboard).
"""

import json
import os
import statistics

from multi_log import load_log

LEADERBOARD_PATH = "state/model_leaderboard.json"
CALIBRATION_PATH = "state/ensemble_calibration.json"
TUNING_REPORT_PATH = "state/tuning_report.json"
OUTPUT_PATH = "docs/data.json"


def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_performance_over_time(resolved_entries):
    """Running (cumulative) average main-hits per strategy, in chronological
    order, for the '📈 Biểu đồ hiệu năng theo thời gian' chart."""
    strategy_names = set()
    for e in resolved_entries:
        strategy_names.update(e["hits"].keys())
    strategy_names = sorted(strategy_names)

    running_sums = {name: 0.0 for name in strategy_names}
    running_counts = {name: 0 for name in strategy_names}
    series = {name: [] for name in strategy_names}
    labels = []

    for e in resolved_entries:
        labels.append(e["target_draw_id"])
        for name in strategy_names:
            h = e["hits"].get(name)
            if h is not None:
                running_sums[name] += h["main_hits"]
                running_counts[name] += 1
            avg = (running_sums[name] / running_counts[name]) if running_counts[name] else None
            series[name].append(round(avg, 4) if avg is not None else None)

    return {"labels": labels, "series": series}


def build_model_accuracy(resolved_entries):
    strategy_names = set()
    for e in resolved_entries:
        strategy_names.update(e["hits"].keys())

    summary = {}
    for name in sorted(strategy_names):
        hits_list = [e["hits"][name]["main_hits"] for e in resolved_entries if name in e["hits"]]
        special_list = [e["hits"][name]["special_hit"] for e in resolved_entries if name in e["hits"]]
        if not hits_list:
            continue
        summary[name] = {
            "n": len(hits_list),
            "avg_main_hits": round(statistics.mean(hits_list), 4),
            "special_hit_rate": round(statistics.mean(special_list), 4),
        }
    return summary


def build_draw_history(resolved_entries, limit=50):
    rows = []
    for e in reversed(resolved_entries[-limit:]):
        hits = e.get("hits", {})

        def entry(label, main, special, hits_key, meta=False):
            h = hits.get(hits_key) or {}
            return {
                "label": label,
                "main": main,
                "special": special,
                "main_hits": h.get("main_hits"),
                "special_hit": bool(h.get("special_hit")) if h else None,
                "meta": meta,
            }

        # Every prediction made for this draw: ensemble, the reference /
        # comparison predictions, and each individual strategy -- so the
        # dashboard can show all of them, not just the ensemble.
        predictions = [entry("Ensemble", e["ensemble"]["main"], e["ensemble"]["special"], "ensemble", meta=True)]

        for key in ("random_fair", "random_repeat", "nhanaz"):
            r = (e.get("references") or {}).get(key)
            if r and r.get("main"):
                predictions.append(entry(r.get("label") or key, r["main"], r["special"], f"ref_{key}", meta=True))
        # legacy: older entries had a single "hunter" block
        hunter = e.get("hunter")
        if hunter and hunter.get("main"):
            predictions.append(entry("Jackpot Hunter", hunter["main"], hunter["special"], "jackpot_hunter", meta=True))

        n_pinned = len(predictions)  # Ensemble + references/hunter stay on top
        for name, pick in (e.get("per_strategy") or {}).items():
            predictions.append(entry(name, pick["main"], pick["special"], name))

        head, tail = predictions[:n_pinned], predictions[n_pinned:]
        tail.sort(key=lambda p: (-(p["main_hits"] or 0), p["label"]))

        rows.append({
            "target_draw_id": e["target_draw_id"],
            "draw_date": e["actual"]["draw_date"],
            "actual_main": e["actual"]["main"],
            "actual_special": e["actual"]["special"],
            # kept for backward compatibility with the summary row
            "ensemble_predicted_main": e["ensemble"]["main"],
            "ensemble_predicted_special": e["ensemble"]["special"],
            "ensemble_main_hits": hits.get("ensemble", {}).get("main_hits"),
            "ensemble_special_hit": bool(hits.get("ensemble", {}).get("special_hit")),
            "predictions": head + tail,
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
        "leaderboard": _read_json(LEADERBOARD_PATH),
        "ensemble_calibration": _read_json(CALIBRATION_PATH),
        "tuning_report": _read_json(TUNING_REPORT_PATH),
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
