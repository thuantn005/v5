"""
model.py
--------
Shared scoring logic for the Lotto 5/35 "hybrid frequency + gap" heuristic.

IMPORTANT HONESTY NOTE
----------------------
Lotto 5/35 draws are independent random events. Every 5-number combination
(from 1-35) and every special number (1-12) has an equal chance of being
drawn regardless of past history. This module produces a *heuristic score*
based on rolling-window frequency and "overdue" gap length -- the same kind
of scoring used in prior manual backtests, which consistently found results
indistinguishable from random chance.

The score is NOT a probability estimate. It is only used to (a) generate a
pick, and (b) measure how unusually "extreme" this round's numbers look
relative to the model's own history, so we can throttle notifications to
rare occasions instead of spamming every draw.
"""

from __future__ import annotations
import json
import statistics
from dataclasses import dataclass
from typing import Iterable

MAIN_MIN, MAIN_MAX = 1, 35
SPECIAL_MIN, SPECIAL_MAX = 1, 12

DEFAULT_WINDOW = 100      # rolling window size (draws) for frequency
FREQ_WEIGHT = 0.5
GAP_WEIGHT = 0.5


@dataclass
class Draw:
    draw_id: str
    draw_date: str
    numbers: list[int]        # 5 main numbers
    special: int               # 1 special number


def parse_draws(rows: Iterable[dict]) -> list[Draw]:
    """Parse CSV rows (as dicts) from the dataset into Draw objects,
    sorted chronologically by draw_id."""
    draws = []
    for row in rows:
        try:
            result = json.loads(row["result_json"])
            numbers = sorted(int(n) for n in result["numbers"])
            special_list = result.get("special_numbers") or []
            special = int(special_list[0]) if special_list else None
            if special is None or len(numbers) != 5:
                continue
            draws.append(
                Draw(
                    draw_id=row["draw_id"],
                    draw_date=row["draw_date"],
                    numbers=numbers,
                    special=special,
                )
            )
        except (KeyError, ValueError, json.JSONDecodeError, TypeError):
            continue
    draws.sort(key=lambda d: d.draw_id)
    return draws


def _zscore(values: dict[int, float]) -> dict[int, float]:
    nums = list(values.values())
    if len(nums) < 2:
        return {k: 0.0 for k in values}
    mean = statistics.mean(nums)
    stdev = statistics.pstdev(nums) or 1.0
    return {k: (v - mean) / stdev for k, v in values.items()}


def score_pool(history: list[Draw], pool_min: int, pool_max: int,
               window: int = DEFAULT_WINDOW,
               freq_weight: float = FREQ_WEIGHT,
               gap_weight: float = GAP_WEIGHT,
               use_special: bool = False) -> dict[int, float]:
    """
    Compute a hybrid frequency+gap score for every number in [pool_min, pool_max]
    using only draws in `history` (already time-ordered, oldest -> newest).
    Higher score = "hotter" recently AND/OR more "overdue".
    """
    pool = range(pool_min, pool_max + 1)
    recent = history[-window:] if window else history

    # Frequency within rolling window
    freq = {n: 0 for n in pool}
    for d in recent:
        vals = [d.special] if use_special else d.numbers
        for n in vals:
            if n in freq:
                freq[n] += 1

    # Gap = draws since number last appeared (within full history, not just window)
    gap = {n: len(history) for n in pool}  # default: never seen -> max gap
    for idx, d in enumerate(reversed(history)):
        vals = [d.special] if use_special else d.numbers
        for n in vals:
            if n in gap and gap[n] == len(history):
                gap[n] = idx
        if all(g != len(history) for g in gap.values()):
            break

    freq_z = _zscore(freq)
    gap_z = _zscore(gap)

    score = {
        n: freq_weight * freq_z[n] + gap_weight * gap_z[n]
        for n in pool
    }
    return score


def predict_next(history: list[Draw], window: int = DEFAULT_WINDOW) -> dict:
    """Generate the next-draw prediction plus an internal confidence metric."""
    main_scores = score_pool(history, MAIN_MIN, MAIN_MAX, window, use_special=False)
    special_scores = score_pool(history, SPECIAL_MIN, SPECIAL_MAX, window, use_special=True)

    ranked_main = sorted(main_scores.items(), key=lambda kv: kv[1], reverse=True)
    ranked_special = sorted(special_scores.items(), key=lambda kv: kv[1], reverse=True)

    top5 = [n for n, _ in ranked_main[:5]]
    top_special = ranked_special[0][0]

    # Internal confidence metric: how far the top-5 scores are pulled away
    # from the rest of the pool (sum of top-5 z minus mean of remaining z).
    top5_scores = [s for _, s in ranked_main[:5]]
    rest_scores = [s for _, s in ranked_main[5:]]
    rest_mean = statistics.mean(rest_scores) if rest_scores else 0.0
    confidence = sum(top5_scores) - 5 * rest_mean

    return {
        "main_numbers": sorted(top5),
        "special_number": top_special,
        "confidence": confidence,
        "main_score_table": dict(sorted(main_scores.items())),
        "special_score_table": dict(sorted(special_scores.items())),
    }


def match_count(predicted_main: list[int], predicted_special: int, actual: Draw) -> dict:
    main_hits = len(set(predicted_main) & set(actual.numbers))
    special_hit = int(predicted_special == actual.special)
    return {"main_hits": main_hits, "special_hit": special_hit}
