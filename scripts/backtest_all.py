"""
backtest_all.py
-----------------
Walk-forward backtest of every strategy in strategies.py, plus a true
random baseline, over the full history. For each strategy we compute:

  - hit-count distribution (how many main numbers matched, 0-5)
  - average main hits
  - special-number hit rate
  - a binomial p-value comparing observed vs the THEORETICAL random
    baseline (hypergeometric: picking 5 of 35, expected overlap with
    the actual 5 drawn = 5*5/35 = 5/7 ~= 0.7143)

This is the honest alternative to the reference repo's ROI metric, which
we've verified is dominated by rare high-tier jackpot hits and therefore
tells you almost nothing about real skill (see README).

Output: state/model_leaderboard.json
"""

import csv
import json
import math
import statistics
from collections import Counter

from model import parse_draws, match_count, MAIN_MIN, MAIN_MAX, SPECIAL_MIN, SPECIAL_MAX, MAIN_K, SPECIAL_K, Draw
from strategies import STRATEGIES, DEFAULT_PARAMS, pick_topk, random_baseline

DATA_PATH = "data/all.csv"
OUTPUT_PATH = "state/model_leaderboard.json"
TUNED_PARAMS_PATH = "state/tuned_params.json"
MIN_HISTORY = 60

# Exact theoretical values for random 5-of-35 picks against a real 5-number draw
POOL_N, DRAWN_K, PICK_K = 35, 5, 5
EXPECTED_RANDOM_HITS = PICK_K * DRAWN_K / POOL_N  # = 5/7 ~= 0.7143
SPECIAL_RANDOM_RATE = 1 / 12  # ~= 0.0833


def load_draws():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return parse_draws(rows)


def load_tuned_params():
    try:
        with open(TUNED_PARAMS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _z_test_mean(observed_mean: float, n: int, expected_mean: float, expected_var: float) -> float:
    """Two-sided p-value (normal approximation) for observed average hits
    vs the theoretical random-baseline mean, given n backtested draws."""
    if n <= 1:
        return 1.0
    se = math.sqrt(expected_var / n)
    if se == 0:
        return 1.0
    z = (observed_mean - expected_mean) / se
    # two-sided p-value via normal CDF approximation (erf-based, no scipy dependency)
    p = math.erfc(abs(z) / math.sqrt(2))
    return p


def _hypergeom_variance(N, K, n) -> float:
    """Variance of hits when picking n numbers from a pool of N with K 'successes'
    (i.e. drawing without replacement) -- hypergeometric variance formula."""
    if N <= 1:
        return 0.0
    p = K / N
    return n * p * (1 - p) * (N - n) / (N - 1)


def backtest_strategy(draws, strategy_fn, params, rng=None):
    main_hits_list = []
    special_hits_list = []
    history = []
    for d in draws:
        idx = len(history)
        if idx >= MIN_HISTORY:
            main_scores = strategy_fn(history, MAIN_MIN, MAIN_MAX, MAIN_K, False, params, **({"rng": rng} if rng else {}))
            special_scores = strategy_fn(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True, params, **({"rng": rng} if rng else {}))
            pred_main = pick_topk(main_scores, 5)
            pred_special = pick_topk(special_scores, 1)[0]
            hits = match_count(pred_main, pred_special, d)
            main_hits_list.append(hits["main_hits"])
            special_hits_list.append(hits["special_hit"])
        history.append(d)
    return main_hits_list, special_hits_list


def evaluate(main_hits_list, special_hits_list):
    n = len(main_hits_list)
    if n == 0:
        return None
    avg_main = statistics.mean(main_hits_list)
    special_rate = statistics.mean(special_hits_list)
    dist = Counter(main_hits_list)

    var = _hypergeom_variance(POOL_N, DRAWN_K, PICK_K)
    p_value = _z_test_mean(avg_main, n, EXPECTED_RANDOM_HITS, var)

    return {
        "n_backtested": n,
        "avg_main_hits": round(avg_main, 4),
        "expected_random_main_hits": round(EXPECTED_RANDOM_HITS, 4),
        "diff_vs_random": round(avg_main - EXPECTED_RANDOM_HITS, 4),
        "p_value_vs_random": round(p_value, 4),
        "significant_at_0.05": p_value < 0.05,
        "special_hit_rate": round(special_rate, 4),
        "expected_random_special_rate": round(SPECIAL_RANDOM_RATE, 4),
        "main_hit_distribution": {str(k): dist.get(k, 0) for k in range(6)},
    }


def main():
    draws = load_draws()
    if len(draws) < MIN_HISTORY + 20:
        print("Not enough history yet for a meaningful backtest.")
        return

    tuned_params = load_tuned_params()
    results = {}

    for name, fn in STRATEGIES.items():
        params = tuned_params.get(name, DEFAULT_PARAMS.get(name, {}))
        main_hits, special_hits = backtest_strategy(draws, fn, params)
        results[name] = evaluate(main_hits, special_hits)
        print(f"{name:20s}: avg_hits={results[name]['avg_main_hits']:.4f} "
              f"(random~{EXPECTED_RANDOM_HITS:.4f}), p={results[name]['p_value_vs_random']:.4f}, "
              f"special_rate={results[name]['special_hit_rate']:.4f}")

    # True random baseline (multiple repeats for a stable estimate, uses its own RNG state)
    import random
    rng = random.Random(42)
    all_main, all_special = [], []
    n_repeats = 10
    for _ in range(n_repeats):
        m, s = backtest_strategy(draws, random_baseline, {}, rng=rng)
        all_main.extend(m)
        all_special.extend(s)
    results["random_baseline"] = evaluate(all_main, all_special)
    print(f"{'random_baseline':20s}: avg_hits={results['random_baseline']['avg_main_hits']:.4f} "
          f"(random~{EXPECTED_RANDOM_HITS:.4f}), p={results['random_baseline']['p_value_vs_random']:.4f}")

    # Rank by avg_main_hits (informational only -- see README caveat about
    # not over-interpreting small differences as real skill)
    ranking = sorted(
        [(name, r["avg_main_hits"]) for name, r in results.items() if r],
        key=lambda kv: kv[1], reverse=True,
    )

    output = {
        "results": results,
        "ranking_by_avg_hits": [{"strategy": n, "avg_main_hits": v} for n, v in ranking],
        "note": (
            "Rankings here reflect avg main-number hits vs the exact random "
            "baseline (5/35 pick, expected 0.7143 hits), with a two-sided "
            "p-value. Even a genuinely random strategy will show some "
            "positive or negative deviation by chance across ~700 draws -- "
            "check p_value_vs_random before treating a ranking difference "
            "as a real edge. None of these strategies change actual jackpot "
            "odds, which are fixed at 1-in-324,632 regardless of numbers chosen."
        ),
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\nRanking (avg main hits, informational only -- check p-values above):")
    for name, v in ranking:
        sig = " *" if results[name]["significant_at_0.05"] else ""
        print(f"  {name:20s} {v:.4f}{sig}")


if __name__ == "__main__":
    main()
