"""
model.py
--------
Scoring logic for the Lotto 5/35 heuristic, upgraded to mirror the more
rigorous "balanced signal" methodology published by the same dataset's
author at nhanaz-data.github.io/vietlott-prediction-web (see phuong-phap.html
-> section "Cong thuc cho san pham chon tap so").

Their published formula (3 time windows instead of 1, clipped z-scores,
plus a pair-synergy bonus for combo selection):

    score(n) = 0.40*z_short + 0.30*z_near - 0.15*z_long + 0.15*(gap_ratio - 1)

  - z_short : normalized deviation over the last 50 draws
  - z_near  : normalized deviation over the last 200 draws
  - z_long  : normalized deviation over the full history
  - gap_ratio: (draws since number last appeared) / (expected gap)
  - z-scores are clipped to [-4, 4] so one extreme value can't dominate
  - combo selection adds a small pair-synergy bonus (0.12 * avg positive
    co-occurrence deviation with already-picked numbers), same as theirs

IMPORTANT HONESTY NOTE
----------------------
Lotto 5/35 draws are independent random events. Every 5-number combination
(from 1-35) and every special number (1-12) has an equal chance of being
drawn regardless of past history. The reference project above ran this
exact style of scoring through extensive, carefully-corrected hypothesis
testing (Benjamini-Hochberg, walk-forward with a locked evaluation phase,
paired permutation tests) and its own stated conclusion is: "Chua cach
chon nao thang ngau nhien on dinh" -- no method has beaten random reliably.

Using their more careful formula here is about methodological rigor, not
about expecting better real-world hit rates. The score is NOT a probability
estimate. It's used to (a) generate a pick, and (b) measure how unusually
"extreme" this round's numbers look relative to the model's own history, so
notifications can be throttled to rare occasions instead of firing every draw.
"""

from __future__ import annotations
import json
import math
import statistics
from dataclasses import dataclass
from typing import Iterable

MAIN_MIN, MAIN_MAX = 1, 35
SPECIAL_MIN, SPECIAL_MAX = 1, 12
MAIN_K = 5   # numbers drawn per round, from MAIN pool
SPECIAL_K = 1

SHORT_WINDOW = 50
NEAR_WINDOW = 200
# "long" window = full history

Z_CLIP = 4.0

W_SHORT = 0.40
W_NEAR = 0.30
W_LONG = -0.15
W_GAP = 0.15
PAIR_SYNERGY_WEIGHT = 0.12

DEFAULT_WINDOW = NEAR_WINDOW  # kept for backward-compat callers


@dataclass
class Draw:
    draw_id: str
    draw_date: str
    draw_time: str | None     # "13:00" or "21:00", if known
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
            draw_time = None
            try:
                attrs = json.loads(row.get("attributes_json") or "{}")
                draw_time = attrs.get("draw_time")
            except (ValueError, json.JSONDecodeError, TypeError):
                pass
            draws.append(
                Draw(
                    draw_id=row["draw_id"],
                    draw_date=row["draw_date"],
                    draw_time=draw_time,
                    numbers=numbers,
                    special=special,
                )
            )
        except (KeyError, ValueError, json.JSONDecodeError, TypeError):
            continue
    draws.sort(key=lambda d: d.draw_id)
    return draws


def _clip(x: float, lo: float = -Z_CLIP, hi: float = Z_CLIP) -> float:
    return max(lo, min(hi, x))


def _binomial_z(count: int, n: int, p: float) -> float:
    """Normalized deviation z = (observed - n*p) / sqrt(n*p*(1-p))."""
    if n <= 0:
        return 0.0
    expected = n * p
    var = n * p * (1 - p)
    if var <= 0:
        return 0.0
    return _clip((count - expected) / math.sqrt(var))


def _counts_in_window(history: list[Draw], pool: range, window: int | None,
                       use_special: bool) -> dict[int, int]:
    recent = history[-window:] if window else history
    counts = {n: 0 for n in pool}
    for d in recent:
        vals = [d.special] if use_special else d.numbers
        for n in vals:
            if n in counts:
                counts[n] += 1
    return counts


def _gap(history: list[Draw], pool: range, use_special: bool) -> dict[int, int]:
    """Draws since each number last appeared (0 = appeared in the most recent draw)."""
    gap = {n: len(history) for n in pool}
    for idx, d in enumerate(reversed(history)):
        vals = [d.special] if use_special else d.numbers
        for n in vals:
            if n in gap and gap[n] == len(history):
                gap[n] = idx
        if all(g != len(history) for g in gap.values()):
            break
    return gap


def score_pool(history: list[Draw], pool_min: int, pool_max: int,
               k: int, use_special: bool = False) -> dict[int, float]:
    """
    Balanced-signal score for every number in [pool_min, pool_max], following
    the reference project's 3-window formula. `k` is how many numbers are
    drawn per round from this pool (5 for main, 1 for special) -- needed to
    compute the marginal draw probability p = k / N.
    """
    pool = range(pool_min, pool_max + 1)
    N = pool_max - pool_min + 1
    p = k / N
    n_total = len(history)

    counts_short = _counts_in_window(history, pool, SHORT_WINDOW, use_special)
    counts_near = _counts_in_window(history, pool, NEAR_WINDOW, use_special)
    counts_long = _counts_in_window(history, pool, None, use_special)
    gaps = _gap(history, pool, use_special)

    n_short = min(SHORT_WINDOW, n_total)
    n_near = min(NEAR_WINDOW, n_total)
    n_long = n_total

    expected_gap = 1 / p if p > 0 else N  # average draws between appearances

    score = {}
    for num in pool:
        z_short = _binomial_z(counts_short[num], n_short, p)
        z_near = _binomial_z(counts_near[num], n_near, p)
        z_long = _binomial_z(counts_long[num], n_long, p)
        gap_ratio = gaps[num] / expected_gap if expected_gap > 0 else 0.0
        gap_term = _clip(gap_ratio - 1)

        score[num] = (
            W_SHORT * z_short
            + W_NEAR * z_near
            + W_LONG * z_long
            + W_GAP * gap_term
        )
    return score


def _pair_synergy_table(history: list[Draw], window: int = NEAR_WINDOW) -> dict[tuple[int, int], float]:
    """
    Pairwise co-occurrence deviation for MAIN numbers, using the same style
    of binomial z-score, over a rolling window. Returns z for each unordered
    pair (a, b) with a < b.
    """
    recent = history[-window:] if window else history
    n = len(recent)
    N = MAIN_MAX - MAIN_MIN + 1
    # Probability both a and b appear together in one draw (choosing 5 of N
    # without replacement): p_pair = C(N-2, 3) / C(N, 5), simplified:
    if N < MAIN_K:
        return {}
    p_pair = (MAIN_K * (MAIN_K - 1)) / (N * (N - 1))

    counts: dict[tuple[int, int], int] = {}
    for d in recent:
        nums = d.numbers
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                key = (nums[i], nums[j])
                counts[key] = counts.get(key, 0) + 1

    synergy = {}
    for key, c in counts.items():
        synergy[key] = _binomial_z(c, n, p_pair)
    return synergy


def _pick5_with_synergy(main_scores: dict[int, float], synergy: dict[tuple[int, int], float],
                         mode: str = "top") -> list[int]:
    """Greedy selection of 5 main numbers.
    mode="top": highest-scoring first, with a bonus for positive
        co-occurrence synergy with already-picked numbers (mirrors the
        reference project's approach).
    mode="bottom": the INVERSE selection -- lowest-scoring numbers first
        (numbers the model considers "least due"/"coldest"), and instead of
        favoring pairs that tend to co-occur, it actively avoids them --
        a true mirror-image of the "top" strategy, not just a partial flip.
    """
    remaining = dict(main_scores)
    chosen: list[int] = []

    def positive_synergy_mean(candidate: int, picked: list[int]) -> float:
        if not picked:
            return 0.0
        vals = []
        for p in picked:
            key = (candidate, p) if candidate < p else (p, candidate)
            z = synergy.get(key)
            if z is not None and z > 0:
                vals.append(z)
        return statistics.mean(vals) if vals else 0.0

    for _ in range(5):
        best_num, best_val = None, float("-inf")
        for num, base_score in remaining.items():
            bonus = PAIR_SYNERGY_WEIGHT * positive_synergy_mean(num, chosen)
            if mode == "top":
                adjusted = base_score + bonus
            else:  # bottom: want low base_score AND low pairing-with-crowd
                adjusted = -base_score - bonus
            if adjusted > best_val:
                best_num, best_val = num, adjusted
        chosen.append(best_num)
        del remaining[best_num]

    return chosen


def _pick_top5_with_synergy(main_scores: dict[int, float], synergy: dict[tuple[int, int], float]) -> list[int]:
    return _pick5_with_synergy(main_scores, synergy, mode="top")


def predict_next(history: list[Draw], window: int = DEFAULT_WINDOW) -> dict:
    """Generate the next-draw prediction plus an internal confidence metric,
    using the balanced-signal formula (3 windows + gap + pair synergy).
    Also returns an INVERSE pick (bottom-scoring numbers) for comparison --
    the "chọn ngược lại" (opposite) set, purely for reference/curiosity."""
    main_scores = score_pool(history, MAIN_MIN, MAIN_MAX, k=MAIN_K, use_special=False)
    special_scores = score_pool(history, SPECIAL_MIN, SPECIAL_MAX, k=SPECIAL_K, use_special=True)
    synergy = _pair_synergy_table(history)

    top5 = _pick5_with_synergy(main_scores, synergy, mode="top")
    bottom5 = _pick5_with_synergy(main_scores, synergy, mode="bottom")

    ranked_special = sorted(special_scores.items(), key=lambda kv: kv[1], reverse=True)
    top_special = ranked_special[0][0]
    bottom_special = ranked_special[-1][0]

    ranked_main_all = sorted(main_scores.items(), key=lambda kv: kv[1], reverse=True)
    top5_scores = [main_scores[n] for n in top5]
    rest_scores = [s for n, s in ranked_main_all if n not in top5]
    rest_mean = statistics.mean(rest_scores) if rest_scores else 0.0
    confidence = sum(top5_scores) - 5 * rest_mean

    return {
        "main_numbers": sorted(top5),
        "special_number": top_special,
        "confidence": confidence,
        "inverse_main_numbers": sorted(bottom5),
        "inverse_special_number": bottom_special,
        "main_score_table": dict(sorted(main_scores.items())),
        "special_score_table": dict(sorted(special_scores.items())),
    }


def match_count(predicted_main: list[int], predicted_special: int, actual: Draw) -> dict:
    main_hits = len(set(predicted_main) & set(actual.numbers))
    special_hit = int(predicted_special == actual.special)
    return {"main_hits": main_hits, "special_hit": special_hit}
