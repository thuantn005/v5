"""
ensemble.py
------------
Combines every strategy in strategies.py into a single "ensemble" pick by
min-max normalizing each strategy's per-number scores to [0, 1] and then
averaging across strategies (equal weight). This is "Ensemble Voting" in
the sense that every model gets an equal say in the final ranking; a
number that several different strategies independently favor will rank
higher in the ensemble even if no single strategy is confident about it.

Equal weighting (rather than weighting by backtest performance) is a
deliberate choice: since backtest_all.py shows no strategy reliably beats
random (see state/model_leaderboard.json), weighting by past performance
would just be fitting noise. If a future backtest DOES show a strategy is
significantly better with a stable p-value across many periods, revisit
this.
"""

import csv
import json
import os

from model import parse_draws, MAIN_MIN, MAIN_MAX, SPECIAL_MIN, SPECIAL_MAX, MAIN_K, SPECIAL_K
from strategies import STRATEGIES, DEFAULT_PARAMS, pick_topk

TUNED_PARAMS_PATH = "state/tuned_params.json"


def load_tuned_params():
    try:
        with open(TUNED_PARAMS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _minmax_normalize(scores: dict[int, float]) -> dict[int, float]:
    vals = list(scores.values())
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return {n: 0.5 for n in scores}
    return {n: (v - lo) / (hi - lo) for n, v in scores.items()}


def ensemble_scores(history, pool_min, pool_max, k, use_special, tuned_params=None):
    tuned_params = tuned_params or {}
    per_strategy_normalized = {}
    for name, fn in STRATEGIES.items():
        params = tuned_params.get(name, DEFAULT_PARAMS.get(name, {}))
        raw = fn(history, pool_min, pool_max, k, use_special, params)
        per_strategy_normalized[name] = _minmax_normalize(raw)

    pool = range(pool_min, pool_max + 1)
    ensemble = {n: 0.0 for n in pool}
    for name, norm_scores in per_strategy_normalized.items():
        for n in pool:
            ensemble[n] += norm_scores.get(n, 0.0)
    n_strategies = len(STRATEGIES)
    ensemble = {n: v / n_strategies for n, v in ensemble.items()}
    return ensemble, per_strategy_normalized


def ensemble_predict(history, tuned_params=None):
    tuned_params = tuned_params or load_tuned_params()

    main_ensemble, main_per_strategy = ensemble_scores(
        history, MAIN_MIN, MAIN_MAX, MAIN_K, False, tuned_params
    )
    special_ensemble, special_per_strategy = ensemble_scores(
        history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True, tuned_params
    )

    main_pick = pick_topk(main_ensemble, 5)
    special_pick = pick_topk(special_ensemble, 1)[0]

    # Per-strategy individual picks too, for the dashboard / transparency
    per_strategy_picks = {}
    for name, fn in STRATEGIES.items():
        params = tuned_params.get(name, DEFAULT_PARAMS.get(name, {}))
        m = fn(history, MAIN_MIN, MAIN_MAX, MAIN_K, False, params)
        s = fn(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True, params)
        per_strategy_picks[name] = {
            "main": pick_topk(m, 5),
            "special": pick_topk(s, 1)[0],
        }

    # Ensemble "confidence" (informational): how concentrated the top-5
    # ensemble scores are relative to the rest of the pool.
    ranked = sorted(main_ensemble.items(), key=lambda kv: kv[1], reverse=True)
    top5_scores = [main_ensemble[n] for n in main_pick]
    rest_scores = [s for n, s in ranked if n not in main_pick]
    rest_mean = (sum(rest_scores) / len(rest_scores)) if rest_scores else 0.0
    confidence = sum(top5_scores) - 5 * rest_mean

    return {
        "main_numbers": main_pick,
        "special_number": special_pick,
        "confidence": confidence,
        "per_strategy_picks": per_strategy_picks,
    }


if __name__ == "__main__":
    with open("data/all.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    draws = parse_draws(rows)
    result = ensemble_predict(draws)
    print("Ensemble pick:", result["main_numbers"], "+ special", result["special_number"])
    print("Confidence:", round(result["confidence"], 4))
    print("\nPer-strategy picks:")
    for name, pick in result["per_strategy_picks"].items():
        print(f"  {name:20s}: {pick['main']} + {pick['special']:02d}")
