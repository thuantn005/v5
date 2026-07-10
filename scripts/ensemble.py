"""
ensemble.py
------------
Combines every strategy in strategies.py into a single "ensemble" pick.
Each strategy's per-number scores are min-max normalized to [0, 1], then
merged. Two refinements sit on top of a plain average:

  1. Correlation grouping. Several strategies are near-duplicates (e.g.
     frequency-flavored models tend to rank numbers similarly). Left alone,
     a cluster of three correlated models would out-vote a single distinct
     one 3-to-1 purely by redundancy. So before merging we group strategies
     whose score vectors correlate above a threshold and collapse each group
     to ONE representative (the group's mean), so each *independent* signal
     gets one effective vote.

  2. p-value weighting. Each group's vote is scaled by (1 - p_value) from
     the latest backtest (state/model_leaderboard.json), so a strategy that
     looks more distinguishable from random counts for more.

     ⚠️ HONESTY CAVEAT: backtest_all.py applies a Bonferroni correction and
     (as expected for a genuinely random game) NO strategy is significant
     after it. That means these p-value weights are mostly amplifying random
     deviation, not real skill -- exactly the "fitting noise" risk. We keep
     the weight range deliberately narrow (floored, ~0.1..1.0) and surface
     it on the dashboard so it can't masquerade as an edge. If a strategy
     ever becomes significant-after-correction across many periods, this
     weighting will finally reflect something real; until then it's
     near-uniform on purpose.
"""

import csv
import json
import math
import os

from model import parse_draws, MAIN_MIN, MAIN_MAX, SPECIAL_MIN, SPECIAL_MAX, MAIN_K, SPECIAL_K
from strategies import STRATEGIES, DEFAULT_PARAMS, pick_topk

TUNED_PARAMS_PATH = "state/tuned_params.json"
LEADERBOARD_PATH = "state/model_leaderboard.json"
CORR_THRESHOLD = 0.9   # score-vector correlation above which two models are "the same vote"
WEIGHT_FLOOR = 0.1     # no group's vote is ever fully zeroed


def load_tuned_params():
    try:
        with open(TUNED_PARAMS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def load_pvalue_weights() -> dict[str, float]:
    """weight = clamp(1 - p_value_vs_random, floor, 1) per strategy, from the
    last backtest. Falls back to uniform 0.5 for any strategy without a
    backtest result yet (e.g. before the first backtest run)."""
    try:
        with open(LEADERBOARD_PATH, encoding="utf-8") as f:
            results = json.load(f).get("results", {})
    except (FileNotFoundError, json.JSONDecodeError):
        results = {}
    weights = {}
    for name in STRATEGIES:
        r = results.get(name)
        p = r.get("p_value_vs_random") if r else None
        w = (1.0 - p) if p is not None else 0.5
        weights[name] = max(WEIGHT_FLOOR, min(1.0, w))
    return weights


def _minmax_normalize(scores: dict[int, float]) -> dict[int, float]:
    vals = list(scores.values())
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return {n: 0.5 for n in scores}
    return {n: (v - lo) / (hi - lo) for n, v in scores.items()}


def _pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 1e-12 or vb <= 1e-12:
        return 0.0  # a constant (uniform) score vector correlates with nothing
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / math.sqrt(va * vb)


def _cluster_correlated(per_strategy_normalized, pool, threshold=CORR_THRESHOLD):
    """Greedily group strategies whose normalized score vectors correlate at
    or above `threshold`. Returns a list of groups (lists of strategy names)."""
    names = list(per_strategy_normalized)
    vecs = {nm: [per_strategy_normalized[nm].get(n, 0.0) for n in pool] for nm in names}
    groups, assigned = [], set()
    for nm in names:
        if nm in assigned:
            continue
        group = [nm]
        assigned.add(nm)
        for other in names:
            if other in assigned:
                continue
            if _pearson(vecs[nm], vecs[other]) >= threshold:
                group.append(other)
                assigned.add(other)
        groups.append(group)
    return groups


def ensemble_scores(history, pool_min, pool_max, k, use_special,
                    tuned_params=None, weights=None):
    tuned_params = tuned_params or {}
    per_strategy_normalized = {}
    for name, fn in STRATEGIES.items():
        params = tuned_params.get(name, DEFAULT_PARAMS.get(name, {}))
        raw = fn(history, pool_min, pool_max, k, use_special, params)
        per_strategy_normalized[name] = _minmax_normalize(raw)

    pool = list(range(pool_min, pool_max + 1))
    if weights is None:
        weights = load_pvalue_weights()

    # 1. collapse correlated strategies to one representative each
    groups = _cluster_correlated(per_strategy_normalized, pool)

    # 2. weighted average of group representatives
    ensemble = {n: 0.0 for n in pool}
    total_w = 0.0
    for group in groups:
        rep = {n: sum(per_strategy_normalized[nm].get(n, 0.0) for nm in group) / len(group)
               for n in pool}
        group_w = sum(weights.get(nm, 0.5) for nm in group) / len(group)
        for n in pool:
            ensemble[n] += group_w * rep[n]
        total_w += group_w
    if total_w > 0:
        ensemble = {n: v / total_w for n, v in ensemble.items()}
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
