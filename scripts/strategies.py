"""
strategies.py
--------------
Every previous scoring heuristic (hot/cold numbers, gap z-score, momentum,
markov chains, balanced signal, etc.) has been removed. Across every
backtest run in this project's history, none of them beat random selection
with statistical significance -- so this project now uses exactly ONE
model, and is honest about what it is:

    uniform_seeded -- reproducible, seeded random selection.

This mirrors the baseline approach nhanaz-data itself publishes as part of
its own prediction tooling:
  - https://github.com/NhanAZ-Data/vietlott-data-research
  - https://nhanaz-data.github.io/vietlott-prediction-web/?product=lotto535#du-doan
  (their ledger calls this strategy "uniform_seeded" / "Baseline đồng đều
  có seed" -- see predictions/ledger.jsonl in their prediction-web repo)

WHY A SEED, NOT JUST random.choice(): reproducibility is the entire point.
A ticket is only a fair, auditable comparison baseline if anyone can
recompute the EXACT same numbers from a published trace string -- otherwise
"we picked randomly" is just an unverifiable claim, and results could be
silently re-rolled after the fact until something looks good (the same
data-leakage risk nhanaz-data's hash-chained ledger is designed to prevent).
seed_trace() below produces that trace string; publish it alongside every
ticket. Nothing here changes the real 1-in-324,632 jackpot probability --
it only makes the "no better than random" pick fully verifiable.
"""

from __future__ import annotations
import hashlib
import random


def dataset_fingerprint(history) -> str:
    """A short, deterministic fingerprint of the exact data snapshot used
    to generate a ticket -- included in the seed trace so the seed is
    locked to a specific, checkable state of history (can't be silently
    regenerated against different/later data and still claim the same
    trace)."""
    if not history:
        return "empty"
    last = history[-1]
    raw = f"{len(history)}|{last.draw_id}|{last.draw_date}|{sorted(last.numbers)}|{last.special}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _derive_seed(*parts: str) -> int:
    """Deterministic integer seed from a human-readable trace string."""
    joined = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def seed_trace(target_draw_id: str, fingerprint: str, ticket_index: int, pool_label: str) -> str:
    """The exact string hashed to produce a given pool's random scores for
    one ticket. Publish this so anyone can reproduce the pick:
        seed = int(sha256(trace)[:16], 16); random.Random(seed)
    """
    return f"lotto535|target={target_draw_id}|data={fingerprint}|ticket={ticket_index}|pool={pool_label}"


def uniform_seeded(history, pool_min, pool_max, k, use_special, params=None):
    """
    Deliberately does NOT look at draw history for scoring (it only uses
    `history` to build the fingerprint if no explicit seed was passed) --
    every number gets a uniformly random score, seeded via params['seed']
    or params['trace'] for full reproducibility.
    """
    params = params or {}
    seed = params.get("seed")
    if seed is None:
        trace = params.get("trace") or "lotto535|unseeded"
        seed = _derive_seed(trace)
    rng = random.Random(seed)
    pool = list(range(pool_min, pool_max + 1))
    return {n: rng.random() for n in pool}


def pick_topk(scores: dict[int, float], k: int) -> list[int]:
    """Simple top-k picker. For uniform_seeded the 'score' has no meaning
    beyond breaking the tie deterministically from the seeded RNG stream --
    this just reads off the k numbers the seeded draw favored."""
    ranked = sorted(scores.items(), key=lambda kv: (kv[1], -kv[0]), reverse=True)
    return sorted(n for n, _ in ranked[:k])


# ---------------------------------------------------------------------
# Backtest-only comparison baselines (NOT part of STRATEGIES / real
# predictions) -- kept so backtest_all.py can show uniform_seeded next to
# an unseeded true-random control and a deliberately-worse
# with-replacement control, exactly like before.
# ---------------------------------------------------------------------
def random_baseline(history, pool_min, pool_max, k, use_special, params=None, rng=None):
    """Unseeded true-random control (uses the shared `random` module state,
    or an injected `rng`) -- the honesty check that uniform_seeded's
    reproducible seeding doesn't itself introduce any bias vs plain
    randomness."""
    rng = rng or random
    pool = list(range(pool_min, pool_max + 1))
    return {n: rng.random() for n in pool}


def random_repeat(history, pool_min, pool_max, k, use_special, params=None, rng=None):
    """Same random scores as random_baseline; backtest_all.py's
    backtest_random_repeat() samples WITH replacement from these to
    demonstrate that duplicate slots are strictly worse."""
    rng = rng or random
    return {n: rng.random() for n in range(pool_min, pool_max + 1)}


def pick_with_replacement(pool_min: int, pool_max: int, k: int, rng) -> list[int]:
    """Sample k numbers uniformly WITH replacement (duplicates possible)."""
    return [rng.randint(pool_min, pool_max) for _ in range(k)]


def momentum_seeded(history, pool_min, pool_max, k, use_special, params=None):
    """Momentum-inertia: numbers that appeared more recently get a higher base
    score (linear recency weight over the last 30 draws). Mixed 40/60 with
    seeded random noise so the ticket is fully reproducible from its trace.

    The recency signal has no predictive edge — lottery draws are independent
    — but produces a distinct, history-flavoured ticket that anyone can verify
    and reproduce from the published trace string."""
    params = params or {}
    trace = params.get("trace") or "lotto535|momentum|unseeded"
    seed = _derive_seed(trace)
    rng = random.Random(seed)

    pool = list(range(pool_min, pool_max + 1))

    recency = {n: 0.0 for n in pool}
    lookback = min(len(history), 30)
    if lookback > 0:
        for i, draw in enumerate(history[-lookback:]):
            w = (i + 1) / lookback          # oldest = 1/30, newest = 1.0
            appeared = [draw.special] if use_special else draw.numbers
            for n in appeared:
                if pool_min <= n <= pool_max:
                    recency[n] += w
        max_r = max(recency.values()) or 1.0
        recency = {n: v / max_r for n, v in recency.items()}

    # 40% recency momentum + 60% seeded random
    return {n: 0.4 * recency[n] + 0.6 * rng.random() for n in pool}


def momentum_pure(history, pool_min, pool_max, k, use_special, params=None):
    """Pure momentum: 100% recency-weighted, zero random noise. Picks the numbers
    that appeared most recently across the last 30 draws. Fully deterministic from
    draw history — no seed needed. Tie-breaking is by number value (lower wins)."""
    pool = list(range(pool_min, pool_max + 1))
    recency = {n: 0.0 for n in pool}
    lookback = min(len(history), 30)
    if lookback > 0:
        for i, draw in enumerate(history[-lookback:]):
            w = (i + 1) / lookback
            appeared = [draw.special] if use_special else draw.numbers
            for n in appeared:
                if pool_min <= n <= pool_max:
                    recency[n] += w
        max_r = max(recency.values()) or 1.0
        recency = {n: v / max_r for n, v in recency.items()}
    return recency


def _digit_root(n: int) -> int:
    """Reduce n to a single digit by repeated digit-sum (Vedic Ankashastra)."""
    while n > 9:
        n = sum(int(d) for d in str(n))
    return n


def vedic_chakra(history, pool_min, pool_max, k, use_special, params=None):
    """Vedic Chakra (Ankashastra): scores numbers by the frequency of their
    digital root in recent winning draws. Numbers whose 'vibration' (digit root)
    appeared most often in the last 30 draws get the highest score.
    Fully deterministic from draw history."""
    pool = list(range(pool_min, pool_max + 1))
    root_freq = {r: 0 for r in range(1, 10)}
    lookback = min(len(history), 30)
    for draw in history[-lookback:]:
        nums = [draw.special] if use_special else draw.numbers
        for n in nums:
            r = _digit_root(n) or 9
            root_freq[r] = root_freq.get(r, 0) + 1
    max_f = max(root_freq.values()) or 1
    return {n: root_freq.get(_digit_root(n) or 9, 0) / max_f for n in pool}


def vedic_virahanka(history, pool_min, pool_max, k, use_special, params=None):
    """Virahanka sequence (Indian predecessor to Fibonacci, 7th century CE):
    seeds a Fibonacci-like sequence from the sums of recent draws, maps each
    term into the pool. Numbers appearing earlier in the sequence score higher.
    Fully deterministic from draw history."""
    pool = list(range(pool_min, pool_max + 1))
    pool_size = pool_max - pool_min + 1

    if len(history) < 2:
        a, b = pool_min, pool_min + 1
    elif use_special:
        a, b = history[-1].special, history[-2].special
    else:
        a, b = sum(history[-1].numbers), sum(history[-2].numbers)

    scores = {n: 0.0 for n in pool}
    step = 0
    curr_a, curr_b = int(a), int(b)
    while step < pool_size * 4:
        val = ((curr_a - 1) % pool_size) + pool_min
        if scores[val] == 0.0:          # first time this number appears
            scores[val] = 1.0 / (step + 1)
        curr_a, curr_b = curr_b, curr_a + curr_b
        step += 1
        if all(v > 0 for v in scores.values()):
            break
    return scores


def ramanujan_sigma(history, pool_min, pool_max, k, use_special, params=None):
    """Ramanujan Sigma: scores numbers by their abundancy ratio σ(n)/n (sum of
    divisors / n), a function Ramanujan studied deeply. Numbers sharing a prime
    factor with the last draw's numbers get an extra bonus, making the ticket
    history-sensitive while grounded in pure number theory."""
    from math import gcd

    def sigma(n):
        s = 0
        for i in range(1, int(n ** 0.5) + 1):
            if n % i == 0:
                s += i
                if i != n // i:
                    s += n // i
        return s

    pool = list(range(pool_min, pool_max + 1))
    abundancy = {n: sigma(n) / n for n in pool}
    max_ab = max(abundancy.values())

    bonus = {n: 0.0 for n in pool}
    if history:
        last_nums = [history[-1].special] if use_special else history[-1].numbers
        for n in pool:
            shared = sum(1 for d in last_nums if gcd(n, d) > 1)
            bonus[n] = shared / max(len(last_nums), 1)

    return {n: abundancy[n] / max_ab + 0.3 * bonus[n] for n in pool}


def aryabhata_cycle(history, pool_min, pool_max, k, use_special, params=None):
    """Aryabhata cycle (476 CE): uses the maha-yuga constant 4320 from
    Aryabhata's astronomical system to generate a deterministic cyclic
    sequence seeded from the target draw ID. Each draw yields a distinct
    permutation of the pool."""
    pool = list(range(pool_min, pool_max + 1))
    pool_size = pool_max - pool_min + 1
    base = (int(history[-1].draw_id) + 1) if history else 1
    ARYABHATA = 4320

    scores = {n: 0.0 for n in pool}
    step = 0
    while step < pool_size * 20:
        val = pool_min + (base * ARYABHATA * (step + 1)) % pool_size
        if scores[val] == 0.0:
            scores[val] = 1.0 / (step + 1)
        step += 1
        if all(v > 0 for v in scores.values()):
            break
    return scores


STRATEGIES = {
    "uniform_seeded": uniform_seeded,
    "momentum_seeded": momentum_seeded,
    "momentum_pure": momentum_pure,
    "vedic_chakra": vedic_chakra,
    "vedic_virahanka": vedic_virahanka,
    "ramanujan_sigma": ramanujan_sigma,
    "aryabhata_cycle": aryabhata_cycle,
}

DEFAULT_PARAMS = {
    "uniform_seeded": {"seed": None},
    "momentum_seeded": {"seed": None},
    "momentum_pure": {},
    "vedic_chakra": {},
    "vedic_virahanka": {},
    "ramanujan_sigma": {},
    "aryabhata_cycle": {},
}
