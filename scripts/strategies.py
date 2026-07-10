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


STRATEGIES = {
    "uniform_seeded": uniform_seeded,
    "momentum_seeded": momentum_seeded,
}

DEFAULT_PARAMS = {
    "uniform_seeded": {"seed": None},
    "momentum_seeded": {"seed": None},
}
