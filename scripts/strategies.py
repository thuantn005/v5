"""
strategies.py
--------------
Multiple independent scoring strategies for Lotto 5/35, adapted from the
strategy ideas in vietvudanh/vietlott-data/src/machine_learning/strategies
(originally written for Power 6/55, pool 1-55 pick 6) to this game's pool
(1-35 pick 5, plus a 1-12 special number).

IMPORTANT: we deliberately do NOT copy that repo's ROI-based backtest
metric. That metric is dominated by rare high-tier jackpot hits (a single
lucky 5/6 match is worth 5 billion VND against a ~400M VND total ticket
cost), so a single coincidental win swings "ROI" by >1000% regardless of
strategy quality. Here, evaluation uses honest hit-count distributions
compared against the exact random baseline (see backtest_all.py).

Every strategy exposes the same interface:

    strategy_fn(history: list[Draw], pool_min: int, pool_max: int, k: int,
                use_special: bool, params: dict) -> dict[int, float]

returning a per-number score (higher = more favored by that strategy).
Selection (turning scores into a 5-number ticket) is handled separately in
ensemble.py / backtest_all.py so every strategy can optionally use the same
pair-synergy-aware greedy picker.
"""

from __future__ import annotations
import math
import statistics
from collections import Counter, defaultdict

from model import Draw, _clip, _binomial_z, _counts_in_window, _gap, score_pool as _balanced_signal_score_pool

Z_CLIP = 4.0


def _pool_range(pool_min: int, pool_max: int):
    return range(pool_min, pool_max + 1)


def _values(d: Draw, use_special: bool):
    return [d.special] if use_special else d.numbers


# ---------------------------------------------------------------------
# 1. Hot numbers -- highest raw frequency in a rolling window
# ---------------------------------------------------------------------
def hot_numbers(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    window = params.get("window", 100)
    counts = _counts_in_window(history, _pool_range(pool_min, pool_max), window, use_special)
    return {n: float(c) for n, c in counts.items()}


# ---------------------------------------------------------------------
# 2. Cold numbers -- lowest raw frequency (inverse of hot)
# ---------------------------------------------------------------------
def cold_numbers(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    window = params.get("window", 100)
    counts = _counts_in_window(history, _pool_range(pool_min, pool_max), window, use_special)
    max_c = max(counts.values()) if counts else 0
    return {n: float(max_c - c) for n, c in counts.items()}


# ---------------------------------------------------------------------
# 3. Long absence -- numbers most overdue (largest gap since last seen)
# ---------------------------------------------------------------------
def long_absence(history, pool_min, pool_max, k, use_special, params=None):
    gaps = _gap(history, _pool_range(pool_min, pool_max), use_special)
    return {n: float(g) for n, g in gaps.items()}


# ---------------------------------------------------------------------
# 4. Exponential decay -- recent draws weighted more, decaying by half-life
# ---------------------------------------------------------------------
def exponential_decay(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    half_life = params.get("half_life", 30)  # in draws
    decay = math.log(2) / half_life
    scores = {n: 0.0 for n in _pool_range(pool_min, pool_max)}
    n_total = len(history)
    for idx, d in enumerate(reversed(history)):  # idx=0 is most recent
        weight = math.exp(-decay * idx)
        if weight < 1e-4:
            break
        for n in _values(d, use_special):
            if n in scores:
                scores[n] += weight
    return scores


# ---------------------------------------------------------------------
# 5. Pair frequency -- numbers that most often co-occur with recently hot numbers
# ---------------------------------------------------------------------
def pair_frequency(history, pool_min, pool_max, k, use_special, params=None):
    if use_special:
        # Pairing doesn't really apply to a single special number; fall back
        # to plain hot-numbers behavior for the special pool.
        return hot_numbers(history, pool_min, pool_max, k, use_special, params)

    params = params or {}
    window = params.get("window", 150)
    recent = history[-window:] if window else history

    pair_counts = defaultdict(int)
    single_counts = Counter()
    for d in recent:
        nums = d.numbers
        for n in nums:
            single_counts[n] += 1
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                pair_counts[(nums[i], nums[j])] += 1

    # Score each number by how strongly it co-occurs, on average, with the
    # numbers that are currently "hot" (top-half by single frequency).
    pool = list(_pool_range(pool_min, pool_max))
    ranked_by_freq = sorted(pool, key=lambda n: single_counts.get(n, 0), reverse=True)
    hot_half = set(ranked_by_freq[: max(1, len(pool) // 2)])

    scores = {}
    for n in pool:
        total = 0
        cnt = 0
        for h in hot_half:
            if h == n:
                continue
            key = (n, h) if n < h else (h, n)
            total += pair_counts.get(key, 0)
            cnt += 1
        scores[n] = total / cnt if cnt else 0.0
    return scores


# ---------------------------------------------------------------------
# 6. Markov chain -- likelihood of following the most recent draw's numbers
# ---------------------------------------------------------------------
def markov_chain(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    window = params.get("window", 200)
    recent = history[-window:] if window else history
    pool = list(_pool_range(pool_min, pool_max))

    if len(recent) < 2:
        return {n: 0.0 for n in pool}

    transition = defaultdict(lambda: defaultdict(int))
    for i in range(len(recent) - 1):
        prev_vals = _values(recent[i], use_special)
        next_vals = _values(recent[i + 1], use_special)
        for a in prev_vals:
            for b in next_vals:
                transition[a][b] += 1

    last_state = _values(recent[-1], use_special)
    scores = {n: 0.0 for n in pool}
    for a in last_state:
        row = transition.get(a, {})
        row_total = sum(row.values()) or 1
        for n in pool:
            scores[n] += row.get(n, 0) / row_total
    return scores


# ---------------------------------------------------------------------
# 7. Not-repeat -- deliberately avoid numbers drawn very recently
# ---------------------------------------------------------------------
def not_repeat(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    avoid_last_n = params.get("avoid_last_n", 3)
    pool = list(_pool_range(pool_min, pool_max))
    recently_drawn = set()
    for d in history[-avoid_last_n:]:
        recently_drawn.update(_values(d, use_special))

    # Base score = overall frequency (so it's not pure noise), penalized
    # heavily if drawn within the last `avoid_last_n` draws.
    counts = _counts_in_window(history, _pool_range(pool_min, pool_max), 100, use_special)
    max_c = max(counts.values()) if counts else 1
    scores = {}
    for n in pool:
        base = counts.get(n, 0)
        penalty = max_c * 2 if n in recently_drawn else 0
        scores[n] = float(base - penalty)
    return scores


# ---------------------------------------------------------------------
# 8. Pattern -- favors numbers in historically over-represented range-buckets
# ---------------------------------------------------------------------
def pattern(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    window = params.get("window", 200)
    recent = history[-window:] if window else history
    pool = list(_pool_range(pool_min, pool_max))
    n_pool = len(pool)

    # Split the pool into 5 equal-ish range buckets and count how often
    # each bucket is represented across recent draws.
    n_buckets = min(5, n_pool)
    bucket_size = max(1, n_pool // n_buckets)

    def bucket_of(n):
        idx = (n - pool_min) // bucket_size
        return min(idx, n_buckets - 1)

    bucket_counts = Counter()
    for d in recent:
        for n in _values(d, use_special):
            bucket_counts[bucket_of(n)] += 1
    total = sum(bucket_counts.values()) or 1
    bucket_rate = {b: bucket_counts.get(b, 0) / total for b in range(n_buckets)}
    expected_rate = 1 / n_buckets

    scores = {}
    for n in pool:
        b = bucket_of(n)
        scores[n] = bucket_rate.get(b, 0.0) - expected_rate  # positive = over-represented bucket
    return scores


# ---------------------------------------------------------------------
# 9. Balanced signal -- wraps the existing 3-window formula from model.py
# ---------------------------------------------------------------------
def balanced_signal(history, pool_min, pool_max, k, use_special, params=None):
    return _balanced_signal_score_pool(history, pool_min, pool_max, k=k, use_special=use_special)


# ---------------------------------------------------------------------
# 10. Crowd avoidance -- favors numbers LESS likely to be picked by other
#     players (avoids the 1-31 "birthday range" many casual players lean
#     on). This does NOT change hit probability -- it's about reducing
#     the chance of SPLITTING the jackpot with someone else if you do
#     win, since Vietlott jackpots are shared pari-mutuel among winners.
#     Real "jackpot hunters" internationally use this exact technique
#     (e.g. avoiding 1-31, avoiding straight-line/sequential patterns)
#     precisely because it's the one lever that's actually real: it can't
#     raise YOUR odds, but it can raise your expected payout *conditional
#     on winning*.
# ---------------------------------------------------------------------
def crowd_avoidance(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    birthday_max = params.get("birthday_max", 31)
    pool = list(_pool_range(pool_min, pool_max))
    if birthday_max >= pool_max:
        # No 'safe zone' exists for this pool (e.g. the 1-12 special number,
        # which maps onto calendar months -- no obvious less-crowded zone).
        return {n: 0.5 for n in pool}
    # Smooth gradient (not a hard cutoff): monotonically favors larger
    # numbers, since 32-35 are never picked by birthday-based players at
    # all, and even within 1-31, higher day-numbers (29-31, not valid in
    # every month) are mildly less crowded than 1-12 (which double as
    # "month" picks and get extra attention from casual players).
    scores = {n: float(n) for n in pool}
    return scores


# ---------------------------------------------------------------------
# 11. Random baseline -- NOT used for real prediction; only for backtest comparison
# ---------------------------------------------------------------------
def random_baseline(history, pool_min, pool_max, k, use_special, params=None, rng=None):
    import random
    rng = rng or random
    pool = list(_pool_range(pool_min, pool_max))
    return {n: rng.random() for n in pool}


def pick_topk(scores: dict[int, float], k: int) -> list[int]:
    """Simple greedy top-k picker (no synergy adjustment) -- used for every
    strategy except balanced_signal, which has its own synergy-aware picker
    in model.py."""
    ranked = sorted(scores.items(), key=lambda kv: (kv[1], -kv[0]), reverse=True)
    return sorted(n for n, _ in ranked[:k])


STRATEGIES = {
    "hot_numbers": hot_numbers,
    "cold_numbers": cold_numbers,
    "long_absence": long_absence,
    "exponential_decay": exponential_decay,
    "pair_frequency": pair_frequency,
    "markov_chain": markov_chain,
    "not_repeat": not_repeat,
    "pattern": pattern,
    "balanced_signal": balanced_signal,
    "crowd_avoidance": crowd_avoidance,
}

# Default tunable parameters per strategy (used unless overridden by
# state/tuned_params.json, see tuning.py)
DEFAULT_PARAMS = {
    "hot_numbers": {"window": 100},
    "cold_numbers": {"window": 100},
    "long_absence": {},
    "exponential_decay": {"half_life": 30},
    "pair_frequency": {"window": 150},
    "markov_chain": {"window": 200},
    "not_repeat": {"avoid_last_n": 3},
    "pattern": {"window": 200},
    "balanced_signal": {},
    "crowd_avoidance": {"birthday_max": 31},
}
