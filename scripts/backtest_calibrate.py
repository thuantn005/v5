"""
backtest_calibrate.py
----------------------
Walk-forward backtest of the model in model.py.

For every historical draw t (after a minimum warm-up period), we:
  1. Compute the prediction + confidence score using ONLY draws before t
     (no lookahead / no leakage).
  2. Compare the predicted top-5 + special against the actual draw t.
  3. Record (confidence, main_hits, special_hit).

We use this to:
  - Calibrate NOTIFY_THRESHOLD = the 95th percentile of historical
    confidence values, so alerts only fire on the ~5% of rounds where the
    model's own internal conviction is unusually high.
  - Report the correlation between confidence and actual hits. If this
    correlation is ~0 (which is what every prior manual backtest on this
    data has found), the calibration.json file records that honestly --
    the threshold governs *notification frequency*, not real win odds.

Output: state/calibration.json
"""

import csv
import json
import statistics

from model import parse_draws, predict_next, match_count, DEFAULT_WINDOW

DATA_PATH = "data/all.csv"
OUTPUT_PATH = "state/calibration.json"
MIN_HISTORY = 60          # don't start backtesting until we have this many draws
PERCENTILE_FOR_THRESHOLD = 0.95


def load_draws():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return parse_draws(rows)


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
    draws = load_draws()
    if len(draws) < MIN_HISTORY + 10:
        print(f"Not enough history yet ({len(draws)} draws) -- skipping calibration.")
        return

    confidences, main_hits_list, special_hits_list = [], [], []

    for i in range(MIN_HISTORY, len(draws)):
        history = draws[:i]
        actual = draws[i]
        pred = predict_next(history, window=DEFAULT_WINDOW)
        hits = match_count(pred["main_numbers"], pred["special_number"], actual)
        confidences.append(pred["confidence"])
        main_hits_list.append(hits["main_hits"])
        special_hits_list.append(hits["special_hit"])

    confidences_sorted = sorted(confidences)
    idx = min(len(confidences_sorted) - 1,
              int(PERCENTILE_FOR_THRESHOLD * len(confidences_sorted)))
    threshold = confidences_sorted[idx]

    corr_main = pearson_corr(confidences, main_hits_list)
    corr_special = pearson_corr(confidences, special_hits_list)

    avg_main_hits = statistics.mean(main_hits_list)
    avg_main_hits_high_conf = statistics.mean(
        [h for c, h in zip(confidences, main_hits_list) if c >= threshold]
    ) if any(c >= threshold for c in confidences) else None

    calibration = {
        "n_backtested_draws": len(confidences),
        "notify_threshold_confidence": threshold,
        "correlation_confidence_vs_main_hits": corr_main,
        "correlation_confidence_vs_special_hit": corr_special,
        "avg_main_hits_overall": avg_main_hits,
        "avg_main_hits_when_confidence_above_threshold": avg_main_hits_high_conf,
        "note": (
            "Correlation values near 0 mean the confidence score does NOT "
            "predict actual hit rate any better than chance -- consistent "
            "with every prior backtest on this data. The threshold only "
            "controls how often notifications fire (roughly the top "
            f"{int((1 - PERCENTILE_FOR_THRESHOLD) * 100)}% most 'unusual' "
            "rounds by this heuristic), not a genuine edge."
        ),
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(calibration, f, ensure_ascii=False, indent=2)

    print(json.dumps(calibration, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
