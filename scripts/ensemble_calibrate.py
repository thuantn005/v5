"""
ensemble_calibrate.py
-----------------------
Walk-forward calibration of the ENSEMBLE's confidence score (same idea as
backtest_calibrate.py did for the single balanced_signal model, applied to
the multi-strategy ensemble). Produces the notify threshold used by
run_pipeline.py, plus an honest correlation check against real hits.

Output: state/ensemble_calibration.json
"""

import csv
import json
import statistics

from model import parse_draws, match_count
from ensemble import ensemble_predict, load_tuned_params

DATA_PATH = "data/all.csv"
OUTPUT_PATH = "state/ensemble_calibration.json"
MIN_HISTORY = 60
PERCENTILE_FOR_THRESHOLD = 0.95


def pearson_corr(xs, ys):
    if len(xs) < 2:
        return 0.0
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def main():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    draws = parse_draws(rows)

    if len(draws) < MIN_HISTORY + 10:
        print("Not enough history yet -- skipping ensemble calibration.")
        return

    tuned_params = load_tuned_params()
    confidences, main_hits_list, special_hits_list = [], [], []

    for i in range(MIN_HISTORY, len(draws)):
        history = draws[:i]
        actual = draws[i]
        pred = ensemble_predict(history, tuned_params)
        hits = match_count(pred["main_numbers"], pred["special_number"], actual)
        confidences.append(pred["confidence"])
        main_hits_list.append(hits["main_hits"])
        special_hits_list.append(hits["special_hit"])

    confidences_sorted = sorted(confidences)
    idx = min(len(confidences_sorted) - 1, int(PERCENTILE_FOR_THRESHOLD * len(confidences_sorted)))
    threshold = confidences_sorted[idx]

    corr_main = pearson_corr(confidences, main_hits_list)
    corr_special = pearson_corr(confidences, special_hits_list)

    calibration = {
        "n_backtested_draws": len(confidences),
        "notify_threshold_confidence": threshold,
        "correlation_confidence_vs_main_hits": corr_main,
        "correlation_confidence_vs_special_hit": corr_special,
        "avg_main_hits_overall": statistics.mean(main_hits_list),
        "note": (
            "Same honesty caveat as the single-model calibration: a "
            "correlation near 0 means ensemble confidence does not predict "
            "real hit rate. The threshold only controls notification "
            "frequency (top ~5% most 'unusual' rounds), not a genuine edge."
        ),
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(calibration, f, ensure_ascii=False, indent=2)
    print(json.dumps(calibration, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
