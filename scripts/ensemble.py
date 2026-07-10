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
from strategies import (uniform_seeded, momentum_seeded, momentum_pure,
                        vedic_chakra, vedic_virahanka,
                        ramanujan_sigma, aryabhata_cycle, neural_perceptron,
                        indian_per_slot,
                        pick_topk, dataset_fingerprint, seed_trace)

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
    fp = dataset_fingerprint(history)

    # Momentum ticket: 40% recency-weighted history + 60% seeded random
    trace_m_main = f"lotto535|momentum|target={target_draw_id}|data={fp}|pool=main"
    trace_m_spec = f"lotto535|momentum|target={target_draw_id}|data={fp}|pool=special"
    m_main = momentum_seeded(history, MAIN_MIN, MAIN_MAX, MAIN_K, False, {"trace": trace_m_main})
    m_spec = momentum_seeded(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True, {"trace": trace_m_spec})
    momentum_ticket = {
        "main": pick_topk(m_main, MAIN_K),
        "special": pick_topk(m_spec, 1)[0],
        "seed_trace_main": trace_m_main,
        "seed_trace_special": trace_m_spec,
        "dataset_fingerprint": fp,
        "strategy": "momentum",
        "label": "Quán tính (momentum)",
    }
    tickets.append(momentum_ticket)

    headline = tickets[0]

    per_strategy_picks = {
        f"ticket_{i + 1}": {"main": t["main"], "special": t["special"]}
        for i, t in enumerate(tickets[:3])
    }
    per_strategy_picks["ticket_momentum"] = {
        "main": momentum_ticket["main"],
        "special": momentum_ticket["special"],
    }

    # Vedic Chakra: numbers whose digit root appeared most in last 30 draws
    vc_main = vedic_chakra(history, MAIN_MIN, MAIN_MAX, MAIN_K, False)
    vc_spec = vedic_chakra(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True)
    trace_vc = f"lotto535|vedic-chakra|target={target_draw_id}|data={fp}"
    per_strategy_picks["ticket_vedic_chakra"] = {
        "main": pick_topk(vc_main, MAIN_K),
        "special": pick_topk(vc_spec, 1)[0],
        "trace": trace_vc,
        "label": "Vòng số Vedic (Chakra)",
    }

    # Virahanka (Indian Fibonacci): sequence seeded from recent draw sums
    vv_main = vedic_virahanka(history, MAIN_MIN, MAIN_MAX, MAIN_K, False)
    vv_spec = vedic_virahanka(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True)
    trace_vv = f"lotto535|virahanka|target={target_draw_id}|data={fp}"
    per_strategy_picks["ticket_virahanka"] = {
        "main": pick_topk(vv_main, MAIN_K),
        "special": pick_topk(vv_spec, 1)[0],
        "trace": trace_vv,
        "label": "Dãy Virahanka (Fibonacci Ấn Độ)",
    }

    # Ramanujan Sigma: abundancy σ(n)/n + shared prime factor bonus with last draw
    rs_main = ramanujan_sigma(history, MAIN_MIN, MAIN_MAX, MAIN_K, False)
    rs_spec = ramanujan_sigma(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True)
    trace_rs = f"lotto535|ramanujan-sigma|target={target_draw_id}|data={fp}"
    per_strategy_picks["ticket_ramanujan"] = {
        "main": pick_topk(rs_main, MAIN_K),
        "special": pick_topk(rs_spec, 1)[0],
        "trace": trace_rs,
        "label": "Số học Ramanujan (σ/n)",
    }

    # Aryabhata cycle: deterministic permutation via constant 4320 × draw_id
    ac_main = aryabhata_cycle(history, MAIN_MIN, MAIN_MAX, MAIN_K, False)
    ac_spec = aryabhata_cycle(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True)
    trace_ac = f"lotto535|aryabhata|target={target_draw_id}|data={fp}"
    per_strategy_picks["ticket_aryabhata"] = {
        "main": pick_topk(ac_main, MAIN_K),
        "special": pick_topk(ac_spec, 1)[0],
        "trace": trace_ac,
        "label": "Chu kỳ Aryabhata (4320)",
    }

    # Neural perceptron: transition weight matrix W trained on last 100 draws
    np_main = neural_perceptron(history, MAIN_MIN, MAIN_MAX, MAIN_K, False)
    np_spec = neural_perceptron(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True)
    trace_np = f"lotto535|neural-perceptron|target={target_draw_id}|data={fp}"
    per_strategy_picks["ticket_neural"] = {
        "main": pick_topk(np_main, MAIN_K),
        "special": pick_topk(np_spec, 1)[0],
        "trace": trace_np,
        "label": "Mạng nơ-ron (Perceptron)",
    }

    # Indian per-slot fusion: each of 5 main slots owned by a dedicated Indian
    # mathematics model; special = weighted consensus of all 5 models.
    #   Slot 1 → Vedic Chakra (digital root / Ankashastra)
    #   Slot 2 → Virahanka (Indian Fibonacci, 7th c. CE)
    #   Slot 3 → Ramanujan σ/n (abundancy + prime-factor bonus)
    #   Slot 4 → Aryabhata 4320 (maha-yuga astronomical cycle)
    #   Slot 5 → Neural Perceptron (transition weight matrix)
    ips_main = indian_per_slot(history, MAIN_MIN, MAIN_MAX, MAIN_K, False)
    ips_spec = indian_per_slot(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True)
    trace_ips = f"lotto535|indian-per-slot|target={target_draw_id}|data={fp}"
    per_strategy_picks["ticket_indian_per_slot"] = {
        "main": pick_topk(ips_main, MAIN_K),
        "special": pick_topk(ips_spec, 1)[0],
        "trace": trace_ips,
        "label": "Hợp nhất Toán Ấn Độ (mỗi số 1 model)",
        "slot_labels": [
            "Vedic Chakra", "Virahanka", "Ramanujan σ/n",
            "Aryabhata 4320", "Neural Perceptron",
        ],
    }

    return {
        "main_numbers": headline["main"],
        "special_number": headline["special"],
        "confidence": 0.0,
        "tickets": tickets,
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
