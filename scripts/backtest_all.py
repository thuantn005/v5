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
from strategies import (
    STRATEGIES, DEFAULT_PARAMS, pick_topk, random_baseline,
    random_repeat, pick_with_replacement,
)

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

    # Empirical 95% confidence interval for the observed average main hits
    # (normal approximation, from the sample's own spread). If this interval
    # comfortably straddles 0.7143, the strategy is indistinguishable from
    # random -- a far more intuitive read than the p-value alone.
    sample_sd = statistics.pstdev(main_hits_list) if n > 1 else 0.0
    se = sample_sd / math.sqrt(n) if n > 0 else 0.0
    ci95 = [round(avg_main - 1.96 * se, 4), round(avg_main + 1.96 * se, 4)]

    return {
        "n_backtested": n,
        "avg_main_hits": round(avg_main, 4),
        "avg_main_hits_se": round(se, 4),
        "avg_main_hits_ci95": ci95,
        "expected_random_main_hits": round(EXPECTED_RANDOM_HITS, 4),
        "diff_vs_random": round(avg_main - EXPECTED_RANDOM_HITS, 4),
        "p_value_vs_random": round(p_value, 4),
        "significant_at_0.05": p_value < 0.05,
        # significant_after_bonferroni is filled in by main() once the total
        # number of tested hypotheses is known (multiple-comparison control).
        "significant_after_bonferroni": None,
        "special_hit_rate": round(special_rate, 4),
        "expected_random_special_rate": round(SPECIAL_RANDOM_RATE, 4),
        "main_hit_distribution": {str(k): dist.get(k, 0) for k in range(6)},
    }


def backtest_random_repeat(draws, rng):
    """Walk-forward backtest for the 'random WITH replacement' pick. Because
    duplicates are allowed, we count DISTINCT matched main numbers, which
    naturally penalizes wasted (duplicate) slots."""
    main_hits_list, special_hits_list = [], []
    history = []
    for d in draws:
        if len(history) >= MIN_HISTORY:
            pred_main = pick_with_replacement(MAIN_MIN, MAIN_MAX, MAIN_K, rng)
            pred_special = pick_with_replacement(SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, rng)[0]
            main_hits_list.append(len(set(pred_main) & set(d.numbers)))
            special_hits_list.append(1 if pred_special == d.special else 0)
        history.append(d)
    return main_hits_list, special_hits_list


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

    # Random WITH replacement -- included to show it is strictly worse (wasted
    # duplicate slots), NOT part of the ensemble.
    rng_rep = random.Random(43)
    rep_main, rep_special = [], []
    for _ in range(n_repeats):
        m, s = backtest_random_repeat(draws, rng_rep)
        rep_main.extend(m)
        rep_special.extend(s)
    results["random_repeat"] = evaluate(rep_main, rep_special)
    print(f"{'random_repeat':20s}: avg_hits={results['random_repeat']['avg_main_hits']:.4f} "
          f"(random~{EXPECTED_RANDOM_HITS:.4f}) -- with-replacement, expected < baseline")

    # --- Multiple-comparison control (Bonferroni) ---
    # We test many strategies at once; at alpha=0.05 each, we'd expect ~1 in
    # 20 to look "significant" purely by chance. Bonferroni divides alpha by
    # the number of hypotheses so a strategy must clear a much stricter bar
    # before we call its deviation real.
    tested = [name for name in results if name not in ("random_baseline", "random_repeat")]
    n_hyp = max(1, len(tested))
    bonferroni_alpha = 0.05 / n_hyp
    for name, r in results.items():
        if r:
            r["significant_after_bonferroni"] = r["p_value_vs_random"] < bonferroni_alpha

    # Rank by avg_main_hits (informational only -- see README caveat about
    # not over-interpreting small differences as real skill)
    ranking = sorted(
        [(name, r["avg_main_hits"]) for name, r in results.items() if r],
        key=lambda kv: kv[1], reverse=True,
    )

    output = {
        "results": results,
        "ranking_by_avg_hits": [{"strategy": n, "avg_main_hits": v} for n, v in ranking],
        "n_hypotheses_tested": n_hyp,
        "bonferroni_alpha": round(bonferroni_alpha, 5),
        "note": (
            "Rankings reflect avg main-number hits vs the exact random baseline "
            "(5/35 pick, expected 0.7143 hits), with a two-sided p-value and a "
            "95% confidence interval (avg_main_hits_ci95). Across ~700 draws a "
            "genuinely random strategy still deviates by chance, and testing "
            f"{n_hyp} strategies at once means ~1 would look 'significant' at "
            "0.05 by luck alone -- so significant_after_bonferroni (alpha = "
            f"0.05/{n_hyp} = {round(bonferroni_alpha, 5)}) is the honest bar; a "
            "CI that straddles 0.7143 means indistinguishable from random. "
            "random_repeat samples WITH replacement and should score BELOW the "
            "baseline (duplicates waste slots). None of these change the actual "
            "jackpot odds, fixed at 1-in-324,632 regardless of numbers chosen."
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
