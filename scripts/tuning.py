"""
tuning.py
----------
Auto-tunes each strategy's parameters via a small grid search, using a
train/holdout split (NOT the full history) so tuning can't simply
overfit the entire backtest -- the selected parameters are chosen using
only the TRAIN portion, then re-evaluated on the held-out VALIDATION
portion for an honest out-of-sample report.

This only needs to run periodically (see should_run_tuning() -- default:
at most once every 7 days), not on every twice-daily prediction run,
matching "tự tối ưu tham số (theo lịch)".

Output: state/tuned_params.json (used by backtest_all.py / predict), and
state/tuning_report.json (train vs holdout performance, for transparency).
"""

import csv
import itertools
import json
import os
import statistics
from datetime import datetime, timezone, timedelta

from model import parse_draws, match_count, MAIN_MIN, MAIN_MAX, SPECIAL_MIN, SPECIAL_MAX, MAIN_K, SPECIAL_K
from strategies import STRATEGIES, DEFAULT_PARAMS, pick_topk

DATA_PATH = "data/all.csv"
TUNED_PARAMS_PATH = "state/tuned_params.json"
TUNING_REPORT_PATH = "state/tuning_report.json"
TUNING_STATE_PATH = "state/tuning_schedule.json"
MIN_HISTORY = 60
TUNE_EVERY_DAYS = 7
TRAIN_FRACTION = 0.7

# Small, cheap grids -- kept intentionally narrow so tuning stays fast and
# doesn't itself become a source of overfitting (more options = more
# chances to fit train-set noise).
# Grids for the ACTIVE 3-model roster (see strategies.STRATEGIES). Any model
# not listed here just tunes with its DEFAULT_PARAMS.
PARAM_GRID = {
    "gap_zscore": {},       # no tunable params
    "momentum": {"short_window": [20, 30, 45], "long_window": [90, 120, 180]},
    "crowd_avoidance": {},  # bias model is fixed, not fit to draw history
}


def should_run_tuning() -> bool:
    if not os.path.exists(TUNING_STATE_PATH):
        return True
    try:
        with open(TUNING_STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
        last = datetime.fromisoformat(state["last_tuned_at"])
        return datetime.now(timezone.utc) - last >= timedelta(days=TUNE_EVERY_DAYS)
    except (KeyError, ValueError, json.JSONDecodeError):
        return True


def _mark_tuned():
    with open(TUNING_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"last_tuned_at": datetime.now(timezone.utc).isoformat()}, f, indent=2)


def _grid_combos(grid: dict):
    if not grid:
        yield {}
        return
    keys = list(grid.keys())
    for values in itertools.product(*grid.values()):
        yield dict(zip(keys, values))


def _avg_hits_for_params(draws, fn, params, start_idx, end_idx):
    hits = []
    history = draws[:start_idx]
    for i in range(start_idx, end_idx):
        d = draws[i]
        main_scores = fn(history, MAIN_MIN, MAIN_MAX, MAIN_K, False, params)
        pred_main = pick_topk(main_scores, 5)
        hits.append(match_count(pred_main, 1, d)["main_hits"])
        history.append(d)
    return statistics.mean(hits) if hits else 0.0


def tune_all(draws):
    n = len(draws)
    split = int(n * TRAIN_FRACTION)
    split = max(split, MIN_HISTORY + 10)
    if split >= n - 5:
        print("Not enough history for a meaningful train/holdout tuning split yet.")
        return {}, {}

    tuned_params = {}
    report = {}

    for name, fn in STRATEGIES.items():
        grid = PARAM_GRID.get(name, {})
        best_params, best_train_score = DEFAULT_PARAMS.get(name, {}), float("-inf")

        for combo in _grid_combos(grid):
            score = _avg_hits_for_params(draws, fn, combo, MIN_HISTORY, split)
            if score > best_train_score:
                best_train_score, best_params = score, combo

        holdout_score = _avg_hits_for_params(draws, fn, best_params, split, n)

        tuned_params[name] = best_params
        report[name] = {
            "chosen_params": best_params,
            "train_avg_hits": round(best_train_score, 4),
            "holdout_avg_hits": round(holdout_score, 4),
            "train_draws": split - MIN_HISTORY,
            "holdout_draws": n - split,
        }
        print(f"{name:20s}: params={best_params} train={best_train_score:.4f} holdout={holdout_score:.4f}")

    return tuned_params, report


def main():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    draws = parse_draws(rows)

    if len(draws) < MIN_HISTORY + 30:
        print("Not enough history yet for tuning.")
        return

    if not should_run_tuning():
        print("Tuning was already run within the last "
              f"{TUNE_EVERY_DAYS} days -- skipping (reusing existing tuned_params.json).")
        return

    tuned_params, report = tune_all(draws)
    if not tuned_params:
        return

    with open(TUNED_PARAMS_PATH, "w", encoding="utf-8") as f:
        json.dump(tuned_params, f, ensure_ascii=False, indent=2)
    with open(TUNING_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "tuned_at": datetime.now(timezone.utc).isoformat(),
            "train_fraction": TRAIN_FRACTION,
            "results": report,
            "note": (
                "Params are chosen on the TRAIN split only, then re-scored "
                "on a held-out VALIDATION split never used for selection. "
                "If holdout_avg_hits isn't consistently close to or above "
                "train_avg_hits across strategies, the 'best' params on "
                "train are likely just fitting noise -- expected for a "
                "genuinely random game."
            ),
        }, f, ensure_ascii=False, indent=2)
    _mark_tuned()
    print("\nSaved tuned_params.json and tuning_report.json")


if __name__ == "__main__":
    main()
