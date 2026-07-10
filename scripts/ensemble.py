"""
ensemble.py
------------
No more score-combining "ensemble" of multiple heuristics -- there's only
one model now (strategies.uniform_seeded, see strategies.py for why).

This module generates **3 reproducible tickets** per target draw, each
from its own seed derived from (target_draw_id, dataset_fingerprint,
ticket_index). Every ticket is published with its seed_trace string so
anyone can independently recompute the exact same numbers:

    from strategies import _derive_seed
    seed = _derive_seed(trace_string)
    random.Random(seed)  # -> same scores -> same ticket

This matches nhanaz-data's own "uniform_seeded" baseline approach
(github.com/NhanAZ-Data/vietlott-data-research,
nhanaz-data.github.io/vietlott-prediction-web) and their hash-chained
ledger's anti-leakage principle: a pick is only a fair comparison point if
it's fully reproducible and can't be quietly re-rolled after the fact.

`ensemble_predict()` keeps its old name/return-shape for compatibility
with run_pipeline.py, multi_log.py and generate_dashboard_data.py: ticket 1
is returned as the headline "ensemble" pick, and all 3 tickets are also
exposed under per_strategy_picks (as "ticket_1"/"ticket_2"/"ticket_3") so
the dashboard/log show all of them.
"""

import csv

from model import parse_draws, MAIN_MIN, MAIN_MAX, SPECIAL_MIN, SPECIAL_MAX, MAIN_K, SPECIAL_K
from strategies import uniform_seeded, pick_topk, dataset_fingerprint, seed_trace

N_TICKETS = 3


def load_tuned_params():
    # No tunable params for a seeded-random model -- kept only so
    # run_pipeline.py's existing call site doesn't need changing.
    return {}


def generate_tickets(history, target_draw_id: str, n_tickets: int = N_TICKETS):
    """Returns a list of n_tickets dicts: {main, special, seed_trace_main,
    seed_trace_special}, each independently reproducible."""
    fp = dataset_fingerprint(history)
    tickets = []
    for i in range(1, n_tickets + 1):
        trace_main = seed_trace(target_draw_id, fp, i, "main")
        trace_special = seed_trace(target_draw_id, fp, i, "special")

        main_scores = uniform_seeded(history, MAIN_MIN, MAIN_MAX, MAIN_K, False,
                                      {"trace": trace_main})
        special_scores = uniform_seeded(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True,
                                         {"trace": trace_special})

        tickets.append({
            "main": pick_topk(main_scores, 5),
            "special": pick_topk(special_scores, 1)[0],
            "seed_trace_main": trace_main,
            "seed_trace_special": trace_special,
            "dataset_fingerprint": fp,
        })
    return tickets


def ensemble_predict(history, tuned_params=None):
    """Kept for compatibility with existing call sites. `target_draw_id` is
    derived from history here rather than passed in, matching the old
    signature -- run_pipeline.py can also call generate_tickets() directly
    if it already knows the target id."""
    if not history:
        raise ValueError("need at least one prior draw to derive a target_draw_id")
    width = len(history[-1].draw_id)
    target_draw_id = str(int(history[-1].draw_id) + 1).zfill(width)

    tickets = generate_tickets(history, target_draw_id)
    headline = tickets[0]

    per_strategy_picks = {
        f"ticket_{i + 1}": {"main": t["main"], "special": t["special"]}
        for i, t in enumerate(tickets)
    }

    return {
        "main_numbers": headline["main"],
        "special_number": headline["special"],
        "confidence": 0.0,  # no meaningful concept for a seeded-random pick
        "tickets": tickets,  # full detail incl. seed traces, for the dashboard/log
        "per_strategy_picks": per_strategy_picks,
    }


if __name__ == "__main__":
    with open("data/all.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    draws = parse_draws(rows)
    result = ensemble_predict(draws)
    print("3 bộ vé (chọn ngẫu nhiên có thể lặp lại):\n")
    for i, t in enumerate(result["tickets"], 1):
        print(f"Vé #{i}: {t['main']} + đặc biệt {t['special']:02d}")
        print(f"  seed trace (main):    {t['seed_trace_main']}")
        print(f"  seed trace (special): {t['seed_trace_special']}")
