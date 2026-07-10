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

from model import Draw, _counts_in_window, score_pool as _balanced_signal_score_pool


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
# 2. Bayesian frequency -- posterior mean draw-probability of each number
#    under a Dirichlet/Laplace prior (add-alpha smoothing).
#
#    Replaces the old `cold_numbers`, which was a gambler's-fallacy signal
#    ("rarely drawn -> due"). This is the statistically sound alternative:
#    it just estimates each number's underlying probability honestly. With
#    a symmetric prior the estimate is
#        p_hat(n) = (count(n) + alpha) / (window_draws*k + alpha*pool_size)
#    which shrinks small-sample frequencies toward the uniform 1/pool_size.
#    For a fair lottery every p_hat converges to uniform -- so this makes NO
#    directional "due"/"hot" claim; it simply reports the best-calibrated
#    frequency estimate, and the backtest confirms it's ~random.
# ---------------------------------------------------------------------
def bayesian_frequency(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    window = params.get("window", 200)
    alpha = params.get("alpha", 1.0)  # Laplace (add-one) by default
    pool = list(_pool_range(pool_min, pool_max))
    counts = _counts_in_window(history, _pool_range(pool_min, pool_max), window, use_special)
    total = sum(counts.get(n, 0) for n in pool)
    denom = total + alpha * len(pool)
    return {n: (counts.get(n, 0) + alpha) / denom for n in pool}


# NOTE: chi_square_uniformity was removed as a redundant duplicate -- its
# per-number picks were identical to bayesian_frequency (both are frequency
# residual/estimate signals, correlation >= 0.9), so it added a second copy
# of the same vote without a distinct signal. bayesian_frequency covers it.


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
# 7. Entropy diversity -- score numbers to build a well-SPREAD ticket that
#    maximizes coverage entropy across the number range.
#
#    Replaces the old `not_repeat` ("avoid numbers seen recently"), a
#    gambler's-fallacy signal. This one makes no prediction claim at all:
#    it is a ticket-construction heuristic. We split the pool into equal
#    range-buckets, measure how concentrated recent draws have been per
#    bucket, and favor numbers in the LESS-filled buckets so the greedy
#    top-k picker naturally spreads across the range (higher Shannon
#    entropy of the bucket distribution = more diverse coverage). It does
#    NOT change odds; a spread ticket and a clustered ticket win equally
#    often. Within a bucket, ties break toward individually rarer numbers.
# ---------------------------------------------------------------------
def entropy_diversity(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    window = params.get("window", 150)
    n_buckets = params.get("n_buckets", 5)
    pool = list(_pool_range(pool_min, pool_max))
    n_pool = len(pool)
    n_buckets = max(1, min(n_buckets, n_pool))
    bucket_size = max(1, n_pool // n_buckets)

    def bucket_of(n):
        return min((n - pool_min) // bucket_size, n_buckets - 1)

    counts = _counts_in_window(history, _pool_range(pool_min, pool_max), window, use_special)
    bucket_fill = Counter()
    by_bucket = defaultdict(list)
    for n in pool:
        b = bucket_of(n)
        bucket_fill[b] += counts.get(n, 0)
        by_bucket[b].append(n)

    max_fill = max(bucket_fill.values()) if bucket_fill else 1
    # Give exactly ONE representative per bucket a top tier, so the greedy
    # top-k picker lands one number in each bucket (a maximally SPREAD ticket)
    # rather than dumping all 5 into the single emptiest bucket. Within a
    # bucket the rarest-recently number is the representative; a big
    # rank-based tier keeps every bucket's rep above every non-rep, and
    # bucket sparsity orders the reps among themselves.
    TIER = 1000.0
    scores = {}
    for b, members in by_bucket.items():
        sparsity = max_fill - bucket_fill.get(b, 0)
        members_sorted = sorted(members, key=lambda n: (counts.get(n, 0), n))
        for rank, n in enumerate(members_sorted):
            scores[n] = (TIER * (len(members_sorted) - rank)) + sparsity
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
# ★ gap_zscore -- overdue RELATIVE TO EACH NUMBER'S OWN rhythm.
#   (One of two extra signals added on top of the principled 10.) Unlike a
#   raw "gan" gap, this measures how far a number's CURRENT gap is from that
#   specific number's historical average gap, in units of its own gap
#   standard deviation -- so a number that usually reappears every ~5 draws
#   but has been absent 15 scores high, while a genuinely rare number
#   sitting at its usual long gap does not. Still does not beat random (see
#   backtest); it is a conceptually distinct feature for the ensemble.
# ---------------------------------------------------------------------
def gap_zscore(history, pool_min, pool_max, k, use_special, params=None):
    pool = list(_pool_range(pool_min, pool_max))
    last_idx = {n: None for n in pool}
    gaps = {n: [] for n in pool}
    for idx, d in enumerate(history):
        for n in _values(d, use_special):
            if n in last_idx:
                if last_idx[n] is not None:
                    gaps[n].append(idx - last_idx[n])
                last_idx[n] = idx
    total = len(history)
    scores = {}
    for n in pool:
        cur_gap = (total - 1 - last_idx[n]) if last_idx[n] is not None else total
        seq = gaps[n]
        if len(seq) >= 2:
            mean_g = statistics.mean(seq)
            sd = statistics.pstdev(seq) or 1.0
            scores[n] = (cur_gap - mean_g) / sd
        else:
            scores[n] = 0.0
    return scores


# ---------------------------------------------------------------------
# ★ momentum -- numbers whose SHORT-window frequency is rising above their
#   own LONG-window baseline (trend/acceleration), rather than raw level
#   like hot_numbers. Positive = heating up recently. The second of the two
#   extra signals. Also does not change real odds.
# ---------------------------------------------------------------------
def momentum(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    short_w = params.get("short_window", 30)
    long_w = params.get("long_window", 120)
    pool = list(_pool_range(pool_min, pool_max))
    short_counts = _counts_in_window(history, _pool_range(pool_min, pool_max), short_w, use_special)
    long_counts = _counts_in_window(history, _pool_range(pool_min, pool_max), long_w, use_special)
    ns = max(1, min(short_w, len(history)))
    nl = max(1, min(long_w, len(history)))
    return {n: short_counts.get(n, 0) / ns - long_counts.get(n, 0) / nl for n in pool}


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
def crowd_desirability(n: int, birthday_max: int = 31) -> float:
    """How heavily the general public tends to pick number `n` (higher =
    more crowded = more sharing risk). Based on well-documented lottery
    player biases, not on draw history (the crowd doesn't see the future
    either). Used by crowd_avoidance() and jackpot_hunter.py."""
    d = 0.0
    if n <= birthday_max:
        d += 1.0            # inside the 1-31 "day of month / birthday" range
    if n <= 12:
        d += 0.6            # also a valid month number -> extra popular
    if n <= 9:
        d += 0.3            # single digits are over-picked
    if n in (3, 7, 8, 9):
        d += 0.2            # commonly-considered "lucky" numbers
    return d


def crowd_avoidance(history, pool_min, pool_max, k, use_special, params=None):
    params = params or {}
    birthday_max = params.get("birthday_max", 31)
    pool = list(_pool_range(pool_min, pool_max))
    if birthday_max >= pool_max:
        # No 'safe zone' exists for this pool (e.g. the 1-12 special number,
        # which maps onto calendar months -- no obvious less-crowded zone).
        return {n: 0.5 for n in pool}
    # Score = negative crowd desirability, so the LESS-crowded numbers
    # (32-35 first, then the mid-high range) rank highest. This never
    # changes hit probability -- it only lifts expected payout *conditional
    # on winning* by cutting the odds of splitting the prize.
    return {n: -crowd_desirability(n, birthday_max) for n in pool}


# ---------------------------------------------------------------------
# 11. Random baseline -- NOT used for real prediction; only for backtest comparison
# ---------------------------------------------------------------------
def random_baseline(history, pool_min, pool_max, k, use_special, params=None, rng=None):
    import random
    rng = rng or random
    pool = list(_pool_range(pool_min, pool_max))
    return {n: rng.random() for n in pool}


# ---------------------------------------------------------------------
# 14. Random WITH replacement -- like random_baseline, but the actual pick
#     samples k numbers WITH replacement (duplicates allowed), so a "ticket"
#     may cover FEWER than k distinct numbers. It exists purely to make an
#     honest teaching point in the backtest: sampling with replacement is
#     strictly WORSE than a normal distinct-number ticket, because every
#     duplicate wastes a slot -- expected distinct main hits drop below the
#     0.7143 random-without-replacement baseline. NOT part of the ensemble
#     (it would only inject noise), only backtested for comparison, exactly
#     like random_baseline.
# ---------------------------------------------------------------------
def random_repeat(history, pool_min, pool_max, k, use_special, params=None, rng=None):
    import random
    rng = rng or random
    return {n: rng.random() for n in _pool_range(pool_min, pool_max)}


def pick_with_replacement(pool_min: int, pool_max: int, k: int, rng) -> list[int]:
    """Sample k numbers uniformly WITH replacement (duplicates possible)."""
    return [rng.randint(pool_min, pool_max) for _ in range(k)]


def pick_topk(scores: dict[int, float], k: int) -> list[int]:
    """Simple greedy top-k picker (no synergy adjustment) -- used for every
    strategy except balanced_signal, which has its own synergy-aware picker
    in model.py."""
    ranked = sorted(scores.items(), key=lambda kv: (kv[1], -kv[0]), reverse=True)
    return sorted(n for n, _ in ranked[:k])


# The 10 active ensemble strategies. Three former gambler's-fallacy models
# (cold_numbers, long_absence, not_repeat) were replaced by statistically
# principled counterparts (bayesian_frequency, chi_square_uniformity,
# entropy_diversity). None of these change real win probability; they are
# distinct, defensible signals/heuristics for the ensemble and dashboard.
STRATEGIES = {
    "hot_numbers": hot_numbers,
    "bayesian_frequency": bayesian_frequency,
    "exponential_decay": exponential_decay,
    "pair_frequency": pair_frequency,
    "markov_chain": markov_chain,
    "entropy_diversity": entropy_diversity,
    "pattern": pattern,
    "balanced_signal": balanced_signal,
    "crowd_avoidance": crowd_avoidance,
    # ★ two extra distinct signals (own-rhythm overdue + recent trend)
    "gap_zscore": gap_zscore,
    "momentum": momentum,
}

# Default tunable parameters per strategy (used unless overridden by
# state/tuned_params.json, see tuning.py)
DEFAULT_PARAMS = {
    "hot_numbers": {"window": 100},
    "bayesian_frequency": {"window": 200, "alpha": 1.0},
    "exponential_decay": {"half_life": 30},
    "pair_frequency": {"window": 150},
    "markov_chain": {"window": 200},
    "entropy_diversity": {"window": 150, "n_buckets": 5},
    "pattern": {"window": 200},
    "balanced_signal": {},
    "crowd_avoidance": {"birthday_max": 31},
    "gap_zscore": {},
    "momentum": {"short_window": 30, "long_window": 120},
}
